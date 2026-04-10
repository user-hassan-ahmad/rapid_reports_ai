# SkillSheetCreator — Path A Touchup

**Date:** 2026-04-10
**Component:** `frontend/src/routes/components/SkillSheetCreator.svelte`
**Scope:** Phase 2 (the workbench) only. Phase 1 (paste examples) is untouched.

## Goal

Add high-value polish to the existing wizard without restructuring it. Three concrete upgrades that each solve a real friction, plus restraint everywhere else.

The current wizard is competent. A full rebuild would be lateral. This spec is the 20% of work that delivers ~90% of the realistic value.

## Non-goals

- No new font dependency. RadFlow stays sans-only.
- No accordion / always-visible-stages restructure. The current sliding-stage carousel and `fly` transitions stay.
- No backend changes. Everything is client-side.
- No changes to Phase 1 or to the API surface.

## The three upgrades

### 1. Condensed-summary captions under stage indicator pills

**Problem.** The top stage indicator (Style / Questions / Test / Refine) shows `Style ✓` after completion but nothing about *what was decided*. The user has no glanceable reminder of their state and has to click back into a stage to see.

**Solution.** Beneath each completed stage's pill, show a one-line condensed caption of what the user resolved. Truncates with ellipsis if too long.

**Per-stage caption rules:**

| Stage     | Caption derived from                                                                                                              |
|-----------|-----------------------------------------------------------------------------------------------------------------------------------|
| Style     | First 60 chars of `summary`, ellipsis if longer.                                                                                  |
| Questions | `N answered · M skipped` (e.g. `2 answered · 1 skipped`). When all skipped: `all skipped`. When all answered: `3 answered`.       |
| Test      | First 40 chars of `testFindings.split('\n')[0]`, ellipsis if longer. Empty until user has actually run the test once.             |
| Refine    | `K rules added` where K is the count of `chatHistory` user messages. Hidden when K = 0.                                           |

**Visual.** Caption is `text-[10px] text-gray-500` directly under the pill label, no border or background. Active stage's caption is brighter (`text-gray-400`). Pending stages get no caption.

**Accessibility.** Captions are visual sugar; the pill `aria-label` continues to be the stage name + state.

### 2. Page-outline empty state for the report preview

**Problem.** When `testReport` is empty, the right panel shows two lines of plain gray text. It's the largest piece of real estate on the screen and it sits visually inert until the user generates.

**Solution.** Render an outlined "page" placeholder that previews the *shape* of an upcoming report. Subtle, decorative, intentional.

**Visual.**
- A centered rectangle, max-width matching the prose container (`max-w-2xl`), aspect ratio approximately 1:1.3 (page-like).
- Thin hairline border (`border border-white/10`) with a 1px inner shadow for slight depth.
- Inside: 4–6 horizontal "lines" rendered as thin `bg-white/5` bars at varying widths (mimicking a text block).
- Above the bars: a slightly thicker bar (heading), a thinner bar (subheading).
- Center label below the page outline (where the current "Report will appear here" text lives), in the existing muted gray.
- No animation, no shimmer. Static. Lets the wizard's motion own the visual energy.

**Replaces the existing empty state markup at lines ~632–639** in the current file.

### 3. Per-block diff flash on regenerate

**Problem.** The Refine loop's tightest pain point: user types a correction, regenerates, gets a new wall of markdown, and has to read the entire report to figure out whether their rule landed and what changed.

**Solution.** When a regeneration produces a different report than the previous one, visually flash the changed blocks for ~1.2s, and show a small badge at the top of the preview indicating the change count.

**Implementation:**

#### Block model

Replace the single-blob render of `testReport` with a per-block render:

```svelte
{#each reportBlocks as block (block.id)}
  <div class="report-block" class:flash={block.flash}>
    {@html renderMarkdown(block.text)}
  </div>
{/each}
```

A `block` is `{ id: string, text: string, flash: boolean }`. `id` is a stable hash of the block index + text content (used as a Svelte keyed-each key — when text changes, the key changes, the block re-renders).

#### Splitting

```js
function splitIntoBlocks(report) {
  // Prefer markdown headings if present, else paragraphs.
  if (/^#{1,6}\s/m.test(report)) {
    // Split before each heading line, keep the heading with its content.
    return report.split(/(?=^#{1,6}\s)/m).map(s => s.trim()).filter(Boolean);
  }
  return report.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
}
```

#### Diffing

Pure string comparison block-by-block. No `diff-match-patch` needed for the badge; the existing dependency is available if we later want intra-block character diffs (out of scope here).

```js
function computeFlashSet(prevBlocks, nextBlocks) {
  const prev = new Set(prevBlocks);
  return nextBlocks.map(b => !prev.has(b));  // boolean per next block
}
```

This is order-independent and tolerant of inserted/removed blocks. A block is "flash" if its exact text is not present in the prior report's block set.

#### Badge logic

After regenerate completes:

```js
const prevBlocks = splitIntoBlocks(prevReport);
const nextBlocks = splitIntoBlocks(testReport);
const changedCount = nextBlocks.filter((b, i) => !prevBlocks.includes(b)).length;
const totalCount = nextBlocks.length;
const ratio = totalCount === 0 ? 0 : changedCount / totalCount;

let badge;
if (!prevReport) badge = null;                      // first generation, no badge
else if (changedCount === 0) badge = 'no changes';  // user's rule had no effect
else if (ratio > 0.7) badge = 'regenerated';        // too much changed, badge isn't useful
else badge = `${changedCount} section${changedCount === 1 ? '' : 's'} changed`;
```

The "no changes" badge is intentional — it's a useful negative signal for the user.

#### Flash animation

CSS keyframe: a `border-left: 2px solid rgb(168 85 247)` (purple-500) that fades opacity 1 → 0 over 1200ms, with the rest of the block undisturbed. Removed via class toggle 1300ms after render.

```css
.report-block.flash {
  border-left: 2px solid rgb(168 85 247 / 0.8);
  padding-left: 0.75rem;
  margin-left: -0.75rem;
  animation: diff-flash 1200ms ease-out forwards;
}
@keyframes diff-flash {
  0% { border-left-color: rgb(168 85 247 / 0.9); }
  100% { border-left-color: rgb(168 85 247 / 0); }
}
```

#### Badge UI

Sits in the existing report preview header (the row that contains "REPORT PREVIEW" + copy/edit/regenerate buttons). Inserted left of the action buttons, right of the "REPORT PREVIEW" label. Style: `text-xs text-purple-300 bg-purple-500/10 border border-purple-500/15 rounded-full px-2.5 py-0.5`. Click scrolls the preview container to the first flashed block.

Badge persists until the next regenerate clears it. No manual dismiss.

#### Edge cases

- **First generation** (no `prevReport`): no badge, no flash. `prevReport` is `''` initially.
- **Identical output**: badge reads `no changes`. No blocks flash.
- **>70% changed**: badge reads `regenerated`. All changed blocks still flash (the flash is per-block, not gated by ratio).
- **Empty new report**: shouldn't happen on a successful response, but if it does, render the empty state and skip diff entirely.

## State changes

Add to component state:

```js
let prevReport = '';
/** @type {{ id: string, text: string, flash: boolean }[]} */
let reportBlocks = [];
let diffBadge = /** @type {string | null} */ (null);
```

`runTestGenerate` becomes:

```js
async function runTestGenerate() {
  if (!skillSheet || !testFindings.trim()) return;
  loadingTest = true; error = '';
  prevReport = testReport;     // stash before clearing
  testReport = '';
  try {
    const data = await postJson('/api/templates/skill-sheet/test-generate', { ... });
    if (!data.success) throw new Error(data.error);
    testReport = data.report_content;
    hasGenerated = true;
    updateReportBlocks(prevReport, testReport);
    stage = 'refine';
  } catch (e) { error = e instanceof Error ? e.message : String(e); }
  finally { loadingTest = false; }
}

function updateReportBlocks(prev, next) {
  const prevSplit = prev ? splitIntoBlocks(prev) : [];
  const nextSplit = splitIntoBlocks(next);
  const prevSet = new Set(prevSplit);
  reportBlocks = nextSplit.map((text, i) => ({
    id: `${i}-${hash(text)}`,
    text,
    flash: prev !== '' && !prevSet.has(text)
  }));
  // Compute badge
  const changedCount = reportBlocks.filter(b => b.flash).length;
  if (!prev) diffBadge = null;
  else if (changedCount === 0) diffBadge = 'no changes';
  else if (changedCount / nextSplit.length > 0.7) diffBadge = 'regenerated';
  else diffBadge = `${changedCount} section${changedCount === 1 ? '' : 's'} changed`;

  // Clear flash flags after the animation completes so they don't replay on unrelated re-renders.
  setTimeout(() => {
    reportBlocks = reportBlocks.map(b => ({ ...b, flash: false }));
  }, 1300);
}

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}
```

## File-level diff summary

**Modified files:**
- `frontend/src/routes/components/SkillSheetCreator.svelte` — all three upgrades

**No new files. No package additions.** `diff-match-patch` is already installed but not used in this spec.

## Testing

Manual test plan (this is a UI component, no automated frontend tests in the project):

1. **Caption captions:**
   - Complete Style stage. Verify the Style pill shows a caption with the first 60 chars of the summary.
   - Answer some questions, skip some. Verify Questions pill caption reads `N answered · M skipped`.
   - Edit findings, generate. Verify Test pill caption reads the first line of `testFindings`.
   - Add a refine rule. Verify Refine pill caption reads `1 rule added`.

2. **Empty state:**
   - Open Phase 2 fresh. Verify the page-outline placeholder is centered in the right panel and visible.
   - After first generate, verify the placeholder is replaced by the rendered report.

3. **Diff flash:**
   - Generate a report (first time). Verify no badge appears, no flash.
   - Add a refine rule that should change one section (e.g. "always include a measurement of the largest lesion"). Regenerate. Verify the changed section has a purple left border that fades over ~1.2s, and the badge reads `1 section changed`.
   - Regenerate without changing anything. Verify the badge reads `no changes`.
   - Add a sweeping rule that changes many sections. Verify the badge reads `regenerated`.

## Open questions resolved (for the record)

- **Block split unit:** headings if present, else paragraphs. Resolved.
- **Badge dismissal:** persists until next regenerate. Resolved.
- **First-generation behavior:** no badge, no flash. Resolved.
- **Identical-output behavior:** `no changes` badge (intentional negative signal). Resolved.
- **`diff-match-patch` usage:** not needed for this spec. The library stays installed for future intra-block diffing if we want it.

## Out of scope (deferred)

- Intra-block character-level diff highlights (would use `diff-match-patch`). Defer until the badge alone proves insufficient.
- Live binding from left-panel actions to right-panel highlights (Path B). Defer pending Path A user feedback.
- Phase 1 (paste examples) redesign.
- Calibration Rail accordion restructure (rejected as lateral).
- Mono font introduction (rejected as unnecessary fork).
