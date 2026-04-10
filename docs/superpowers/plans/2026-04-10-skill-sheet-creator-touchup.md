# SkillSheetCreator Path A Touchup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three high-value polish upgrades to `SkillSheetCreator.svelte` Phase 2: condensed-summary captions on stage pills, page-outline empty state for the report preview, and per-block diff flash on regenerate.

**Architecture:** A single new helper module (`reportDiff.js`) holds the pure diff logic and is unit-tested with vitest. The component is modified surgically — state additions, one rewrite of `runTestGenerate`, one swap of the report render block from `{@html testReport}` to a `{#each reportBlocks}` loop, and small markup additions for pill captions / empty state. Three CSS classes are added to `app.css` (the project's existing convention for shared component styles).

**Tech Stack:** Svelte 4, SvelteKit, vitest, Tailwind, marked + DOMPurify (already installed).

**Spec:** `docs/superpowers/specs/2026-04-10-skill-sheet-creator-touchup-design.md`

---

## File Structure

**Created:**
- `frontend/src/lib/utils/reportDiff.js` — pure functions: `splitIntoBlocks`, `hash`, `diffReports`. No Svelte imports, no DOM access.
- `frontend/src/lib/utils/reportDiff.spec.js` — vitest unit tests for the above.

**Modified:**
- `frontend/src/routes/components/SkillSheetCreator.svelte` — state additions, `runTestGenerate` rewrite, per-block render loop, badge UI in preview header, pill caption markup, empty state replacement.
- `frontend/src/app.css` — three new CSS classes: `.report-block`, `.diff-badge`, `.page-outline` (with its child line classes).

**No new dependencies.** `diff-match-patch` is already installed but not used in this plan; the diff is plain string equality at block level.

---

## Task 1: Pure diff helpers + unit tests

**Files:**
- Create: `frontend/src/lib/utils/reportDiff.js`
- Create: `frontend/src/lib/utils/reportDiff.spec.js`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/utils/reportDiff.spec.js`:

```js
import { describe, it, expect } from 'vitest';
import { splitIntoBlocks, diffReports, hash } from './reportDiff.js';

describe('splitIntoBlocks', () => {
	it('returns empty array for empty input', () => {
		expect(splitIntoBlocks('')).toEqual([]);
	});

	it('splits by headings when present', () => {
		const report = '## FINDINGS\nfoo\n\n## IMPRESSION\nbar';
		expect(splitIntoBlocks(report)).toEqual(['## FINDINGS\nfoo', '## IMPRESSION\nbar']);
	});

	it('preserves text before the first heading as its own block', () => {
		const report = 'intro line\n\n## FINDINGS\nfoo';
		expect(splitIntoBlocks(report)).toEqual(['intro line', '## FINDINGS\nfoo']);
	});

	it('falls back to paragraph splits when no headings are present', () => {
		const report = 'first paragraph\n\nsecond paragraph\n\nthird';
		expect(splitIntoBlocks(report)).toEqual(['first paragraph', 'second paragraph', 'third']);
	});

	it('handles a single block', () => {
		expect(splitIntoBlocks('one block')).toEqual(['one block']);
	});
});

describe('hash', () => {
	it('produces stable hashes for the same input', () => {
		expect(hash('hello')).toBe(hash('hello'));
	});

	it('produces different hashes for different input', () => {
		expect(hash('a')).not.toBe(hash('b'));
	});
});

describe('diffReports', () => {
	it('first generation has no badge and no flashes', () => {
		const result = diffReports('', '## A\nfoo\n\n## B\nbar');
		expect(result.badge).toBeNull();
		expect(result.blocks.every((b) => !b.flash)).toBe(true);
		expect(result.blocks).toHaveLength(2);
	});

	it('identical regeneration shows "no changes"', () => {
		const report = '## A\nfoo\n\n## B\nbar';
		const result = diffReports(report, report);
		expect(result.badge).toBe('no changes');
		expect(result.blocks.every((b) => !b.flash)).toBe(true);
	});

	it('single section change reports "1 section changed"', () => {
		const prev = '## A\nfoo\n\n## B\nbar';
		const next = '## A\nfoo\n\n## B\nbaz';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('1 section changed');
		expect(result.blocks[0].flash).toBe(false);
		expect(result.blocks[1].flash).toBe(true);
	});

	it('multi-section change reports plural form', () => {
		const prev = '## A\nfoo\n\n## B\nbar\n\n## C\nbaz\n\n## D\nqux\n\n## E\nquux';
		const next = '## A\nFOO\n\n## B\nBAR\n\n## C\nbaz\n\n## D\nqux\n\n## E\nquux';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('2 sections changed');
	});

	it('majority change reports "regenerated"', () => {
		const prev = '## A\nfoo\n\n## B\nbar\n\n## C\nbaz';
		const next = '## A\nFOO\n\n## B\nBAR\n\n## C\nBAZ';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('regenerated');
		expect(result.blocks.every((b) => b.flash)).toBe(true);
	});

	it('block ids are unique even when block text repeats', () => {
		const result = diffReports('', 'same\n\nsame');
		const ids = result.blocks.map((b) => b.id);
		expect(new Set(ids).size).toBe(ids.length);
	});
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && bun run test:unit -- --run src/lib/utils/reportDiff.spec.js
```

Expected: FAIL with module-not-found error for `./reportDiff.js`.

- [ ] **Step 3: Implement the helpers**

Create `frontend/src/lib/utils/reportDiff.js`:

```js
/**
 * Split a markdown report into logical blocks for per-block diffing.
 * Prefers markdown headings if present, falls back to blank-line paragraphs.
 * @param {string} report
 * @returns {string[]}
 */
export function splitIntoBlocks(report) {
	if (!report) return [];
	if (/^#{1,6}\s/m.test(report)) {
		return report
			.split(/(?=^#{1,6}\s)/m)
			.map((s) => s.trim())
			.filter(Boolean);
	}
	return report
		.split(/\n\s*\n/)
		.map((s) => s.trim())
		.filter(Boolean);
}

/**
 * Stable string hash for use as a Svelte each-key.
 * @param {string} s
 * @returns {string}
 */
export function hash(s) {
	let h = 0;
	for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
	return (h >>> 0).toString(36);
}

/**
 * Compute the per-block diff between two markdown reports.
 * Returns the next report's blocks tagged with `flash` (block text not present
 * in the prior report) plus a summary `badge` string.
 *
 * Badge rules:
 *   - prev empty (first generation): null
 *   - identical: 'no changes'
 *   - >70% blocks changed: 'regenerated'
 *   - otherwise: 'N section[s] changed'
 *
 * @param {string} prev
 * @param {string} next
 * @returns {{ blocks: { id: string, text: string, flash: boolean }[], badge: string | null }}
 */
export function diffReports(prev, next) {
	const nextBlocks = splitIntoBlocks(next);
	const prevBlocks = splitIntoBlocks(prev);
	const prevSet = new Set(prevBlocks);
	const isFirst = !prev;
	const blocks = nextBlocks.map((text, i) => ({
		id: `${i}-${hash(text)}`,
		text,
		flash: !isFirst && !prevSet.has(text)
	}));
	const changedCount = blocks.filter((b) => b.flash).length;

	let badge = null;
	if (isFirst) {
		badge = null;
	} else if (changedCount === 0) {
		badge = 'no changes';
	} else if (nextBlocks.length > 0 && changedCount / nextBlocks.length > 0.7) {
		badge = 'regenerated';
	} else {
		badge = `${changedCount} section${changedCount === 1 ? '' : 's'} changed`;
	}

	return { blocks, badge };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd frontend && bun run test:unit -- --run src/lib/utils/reportDiff.spec.js
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/utils/reportDiff.js frontend/src/lib/utils/reportDiff.spec.js
git commit -m "feat(frontend): add reportDiff helpers for per-block diffing"
```

---

## Task 2: Per-block render with flash on regenerate

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` — script section, `runTestGenerate`, report render block
- Modify: `frontend/src/app.css` — add `.report-block` flash class

- [ ] **Step 1: Add the import**

In `frontend/src/routes/components/SkillSheetCreator.svelte`, locate the imports at the top of `<script>` (around line 7) and add:

```js
import { diffReports } from '$lib/utils/reportDiff.js';
```

The full import block becomes:

```js
import { createEventDispatcher } from 'svelte';
import { API_URL } from '$lib/config';
import { token } from '$lib/stores/auth';
import { fade, fly } from 'svelte/transition';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { diffReports } from '$lib/utils/reportDiff.js';
```

- [ ] **Step 2: Add new state variables**

After the existing state declarations (search for `let testReport = '';` around line 47), add immediately below:

```js
// Per-block diff state for the report preview
let prevReport = '';
/** @type {{ id: string, text: string, flash: boolean }[]} */
let reportBlocks = [];
/** @type {string | null} */
let diffBadge = null;
```

- [ ] **Step 3: Rewrite `runTestGenerate` to compute the diff**

Locate `async function runTestGenerate()` (around line 206). Replace its entire body with:

```js
async function runTestGenerate() {
	if (!skillSheet || !testFindings.trim()) return;
	loadingTest = true;
	error = '';
	prevReport = testReport;
	testReport = '';
	try {
		const data = await postJson('/api/templates/skill-sheet/test-generate', {
			skill_sheet: skillSheet,
			scan_type: scanType,
			clinical_history: testClinicalHistory,
			findings_input: testFindings
		});
		if (!data.success) throw new Error(data.error);
		testReport = data.report_content;
		hasGenerated = true;
		const result = diffReports(prevReport, testReport);
		reportBlocks = result.blocks;
		diffBadge = result.badge;
		// Clear flash flags after the animation completes so they don't replay on unrelated re-renders.
		setTimeout(() => {
			reportBlocks = reportBlocks.map((b) => ({ ...b, flash: false }));
		}, 1300);
		stage = 'refine';
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	} finally {
		loadingTest = false;
	}
}
```

- [ ] **Step 4: Replace the report render block**

Locate the existing render (around lines 612–616):

```svelte
{#if testReport}
	<div class="px-6 py-5">
		<div class="prose prose-invert prose-sm max-w-2xl mx-auto">
			{@html renderMarkdown(testReport)}
		</div>
```

Replace the inner `prose` div with a per-block loop:

```svelte
{#if testReport}
	<div class="px-6 py-5">
		<div class="prose prose-invert prose-sm max-w-2xl mx-auto">
			{#each reportBlocks as block (block.id)}
				<div class="report-block" class:flash={block.flash}>
					{@html renderMarkdown(block.text)}
				</div>
			{/each}
		</div>
```

(Leave the rest of the `{#if testReport}` branch — the refinement hint and closing tags — untouched.)

- [ ] **Step 5: Add the flash CSS**

In `frontend/src/app.css`, append after the existing styles:

```css
/* Per-block flash highlight on report regeneration */
.report-block {
	position: relative;
	padding-left: 0.75rem;
	margin-left: -0.75rem;
	border-left: 2px solid transparent;
	transition: border-left-color 200ms ease-out;
}
.report-block.flash {
	animation: diff-flash 1200ms ease-out forwards;
}
@keyframes diff-flash {
	0% {
		border-left-color: rgb(168 85 247 / 0.9);
	}
	100% {
		border-left-color: rgb(168 85 247 / 0);
	}
}
```

- [ ] **Step 6: Verify the dev server still builds and the report renders correctly**

```bash
cd frontend && bun run check
```

Expected: no errors. (Warnings about unused imports are OK if any pre-existed.)

Then start the dev server and manually verify:

```bash
cd frontend && bun run dev
```

1. Open the SkillSheet creator, paste 3 example reports, analyze.
2. Step through to the Test stage, generate a report. Verify it renders correctly with no visible flash (first generation).
3. Go to Refine, add a small rule, regenerate. Verify the changed section(s) get a brief purple left border that fades over ~1.2s.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte frontend/src/app.css
git commit -m "feat(frontend): per-block flash highlight on report regenerate"
```

---

## Task 3: Diff badge in preview header

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` — preview header markup
- Modify: `frontend/src/app.css` — `.diff-badge` class

- [ ] **Step 1: Add the badge to the preview header**

Locate the preview header (around line 567):

```svelte
<!-- Header -->
<div class="flex items-center justify-between px-6 py-3 border-b border-white/[0.06] shrink-0">
	<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Report preview</span>
	{#if testReport}
```

Replace the `<span>` line with a flex group containing the label and the badge:

```svelte
<!-- Header -->
<div class="flex items-center justify-between px-6 py-3 border-b border-white/[0.06] shrink-0">
	<div class="flex items-center gap-3">
		<span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Report preview</span>
		{#if diffBadge}
			<button
				class="diff-badge"
				on:click={scrollToFirstFlash}
				title="Scroll to first changed section"
			>
				<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
				{diffBadge}
			</button>
		{/if}
	</div>
	{#if testReport}
```

- [ ] **Step 2: Add the `scrollToFirstFlash` helper**

In the `<script>` section, add this helper near the other functions (e.g. just below `copyReportWithConfirm`):

```js
function scrollToFirstFlash() {
	if (typeof document === 'undefined') return;
	const first = document.querySelector('.report-block.flash');
	if (first) {
		first.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}
}
```

(If the flash flags have already cleared by the time the user clicks, the query returns null and nothing happens — which is the right behavior.)

- [ ] **Step 3: Add the badge CSS**

Append to `frontend/src/app.css`:

```css
/* Diff badge in the report preview header */
.diff-badge {
	@apply inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs;
	@apply text-purple-300 bg-purple-500/10 border border-purple-500/20;
	@apply hover:bg-purple-500/20 hover:text-purple-200 transition-colors duration-200;
	cursor: pointer;
}
```

- [ ] **Step 4: Verify the badge renders**

```bash
cd frontend && bun run check
```

Expected: no errors.

Manual verification in the dev server:
1. Generate a report (first time) — verify no badge appears.
2. Add a refine rule, regenerate — verify the badge appears with `1 section changed` (or similar) and clicking it scrolls to the first flashed block.
3. Regenerate without changes — verify badge reads `no changes`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte frontend/src/app.css
git commit -m "feat(frontend): diff badge in skill sheet report preview header"
```

---

## Task 4: Stage pill captions

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` — caption helper, stage indicator markup

- [ ] **Step 1: Add the caption derivation helper**

In the `<script>` section, near the other reactive statements (search for `$: stageIdx = stageOrder.indexOf(stage);` around line 71), add immediately below:

```js
function computePillCaptions(summaryText, qs, hasGen, findings, chat) {
	/** @param {string} s @param {number} n */
	const truncate = (s, n) => (s.length > n ? s.slice(0, n).trimEnd() + '…' : s);

	const summaryCap = summaryText ? truncate(summaryText, 60) : '';

	let questionsCap = '';
	if (qs.length > 0) {
		const answered = qs.filter((q) => q.status === 'answered').length;
		const skipped = qs.filter((q) => q.status === 'skipped').length;
		if (answered === qs.length) questionsCap = `${answered} answered`;
		else if (skipped === qs.length) questionsCap = 'all skipped';
		else if (answered + skipped > 0) questionsCap = `${answered} answered · ${skipped} skipped`;
	}

	let testCap = '';
	if (hasGen && findings.trim()) {
		const firstLine = findings.split('\n')[0].trim();
		testCap = truncate(firstLine, 40);
	}

	const ruleCount = chat.filter((m) => m.role === 'user').length;
	const refineCap = ruleCount > 0 ? `${ruleCount} rule${ruleCount === 1 ? '' : 's'} added` : '';

	return { summary: summaryCap, questions: questionsCap, test: testCap, refine: refineCap };
}

$: pillCaptions = computePillCaptions(summary, questions, hasGenerated, testFindings, chatHistory);
```

- [ ] **Step 2: Update the stage indicator markup to render captions**

Locate the stage indicator (around lines 330–351):

```svelte
<!-- Stage indicator -->
<div class="flex items-center gap-1 px-5 py-2.5 border-b border-white/[0.06] shrink-0">
	{#each stageOrder as s, i}
		<button
			class="flex items-center gap-1.5 text-xs transition-all duration-200
				{stage === s ? 'text-white' : (canNavigate[i] ? 'text-gray-500 hover:text-gray-300' : 'text-gray-700')}"
			on:click={() => { if (canNavigate[i]) goToStage(s); }}
			disabled={!canNavigate[i]}
		>
			{#if canNavigate[i] && stage !== s}
				<svg class="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
			{:else if stage === s}
				<span class="w-1.5 h-1.5 rounded-full bg-purple-500"></span>
			{:else}
				<span class="w-1.5 h-1.5 rounded-full bg-gray-700"></span>
			{/if}
			<span>{stageLabels[s]}</span>
		</button>
		{#if i < stageOrder.length - 1}
			<span class="text-gray-700 text-xs mx-0.5">/</span>
		{/if}
	{/each}
</div>
```

Replace it with:

```svelte
<!-- Stage indicator -->
<div class="flex items-start gap-3 px-5 py-2.5 border-b border-white/[0.06] shrink-0">
	{#each stageOrder as s, i}
		<button
			class="flex flex-col items-start gap-0.5 text-xs transition-all duration-200 max-w-[8rem]
				{stage === s ? 'text-white' : canNavigate[i] ? 'text-gray-500 hover:text-gray-300' : 'text-gray-700'}"
			on:click={() => {
				if (canNavigate[i]) goToStage(s);
			}}
			disabled={!canNavigate[i]}
		>
			<span class="flex items-center gap-1.5">
				{#if canNavigate[i] && stage !== s}
					<svg class="w-3 h-3 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" /></svg>
				{:else if stage === s}
					<span class="w-1.5 h-1.5 rounded-full bg-purple-500"></span>
				{:else}
					<span class="w-1.5 h-1.5 rounded-full bg-gray-700"></span>
				{/if}
				<span>{stageLabels[s]}</span>
			</span>
			{#if pillCaptions[s]}
				<span
					class="text-[10px] truncate max-w-full leading-tight pl-3.5
						{stage === s ? 'text-gray-400' : 'text-gray-600'}"
				>
					{pillCaptions[s]}
				</span>
			{/if}
		</button>
	{/each}
</div>
```

Note: the `/` separators between pills are removed in this layout because they read awkwardly with the captions hanging below. The increased horizontal `gap-3` provides visual separation instead.

- [ ] **Step 3: Verify the captions render**

```bash
cd frontend && bun run check
```

Expected: no errors.

Manual verification in the dev server:
1. After analyzing examples, verify the Style pill shows a truncated 60-char caption from the summary.
2. Answer one question, skip one — verify Questions pill caption reads `1 answered · 1 skipped`.
3. Answer all — verify it reads `N answered`.
4. Generate a report — verify Test pill caption shows the first line of findings (truncated).
5. Add a refine rule — verify Refine pill caption reads `1 rule added`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte
git commit -m "feat(frontend): condensed-summary captions on skill sheet stage pills"
```

---

## Task 5: Page-outline empty state

**Files:**
- Modify: `frontend/src/routes/components/SkillSheetCreator.svelte` — empty state markup
- Modify: `frontend/src/app.css` — `.page-outline` and child line classes

- [ ] **Step 1: Replace the empty state markup**

Locate the empty state branch (around lines 632–639):

```svelte
{:else}
	<div class="flex items-center justify-center h-full">
		<div class="text-center">
			<p class="text-sm text-gray-500">Report will appear here</p>
			<p class="text-xs text-gray-500 mt-1">Complete the steps on the left, then generate</p>
		</div>
	</div>
{/if}
```

Replace with:

```svelte
{:else}
	<div class="flex items-center justify-center h-full px-6">
		<div class="flex flex-col items-center gap-5">
			<div class="page-outline" aria-hidden="true">
				<div class="page-line page-line-heading"></div>
				<div class="page-line page-line-subheading"></div>
				<div class="page-line"></div>
				<div class="page-line page-line-short"></div>
				<div class="page-line"></div>
				<div class="page-line page-line-medium"></div>
				<div class="page-line page-line-short"></div>
			</div>
			<div class="text-center">
				<p class="text-sm text-gray-500">Report will appear here</p>
				<p class="text-xs text-gray-600 mt-1">Complete the steps on the left, then generate</p>
			</div>
		</div>
	</div>
{/if}
```

- [ ] **Step 2: Add the page outline CSS**

Append to `frontend/src/app.css`:

```css
/* Page-outline empty state for the report preview */
.page-outline {
	width: 14rem;
	aspect-ratio: 1 / 1.3;
	border: 1px solid rgb(255 255 255 / 0.08);
	border-radius: 4px;
	background: rgb(255 255 255 / 0.015);
	padding: 1.25rem 1rem;
	display: flex;
	flex-direction: column;
	gap: 0.5rem;
	box-shadow: inset 0 0 0 1px rgb(255 255 255 / 0.02);
}
.page-line {
	height: 6px;
	border-radius: 2px;
	background: rgb(255 255 255 / 0.05);
	width: 100%;
}
.page-line-heading {
	height: 9px;
	width: 60%;
	background: rgb(255 255 255 / 0.08);
	margin-bottom: 0.25rem;
}
.page-line-subheading {
	height: 6px;
	width: 35%;
	background: rgb(255 255 255 / 0.06);
	margin-bottom: 0.5rem;
}
.page-line-short {
	width: 50%;
}
.page-line-medium {
	width: 75%;
}
```

- [ ] **Step 3: Verify the empty state renders**

```bash
cd frontend && bun run check
```

Expected: no errors.

Manual verification: open the SkillSheet creator, get to Phase 2, before clicking "Generate report" verify that the right panel shows the outlined page placeholder centered with the heading/subheading bars and several text-line bars below it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/components/SkillSheetCreator.svelte frontend/src/app.css
git commit -m "feat(frontend): page-outline empty state for skill sheet report preview"
```

---

## Task 6: Final verification

**Files:** none modified

- [ ] **Step 1: Run the unit tests**

```bash
cd frontend && bun run test:unit -- --run src/lib/utils/reportDiff.spec.js
```

Expected: all 13 tests PASS.

- [ ] **Step 2: Run the type checker**

```bash
cd frontend && bun run check
```

Expected: 0 errors. Pre-existing warnings (if any) are acceptable.

- [ ] **Step 3: Run the linter**

```bash
cd frontend && bun run lint
```

Expected: PASS. If prettier complains about formatting in the modified files, run `bun run prettier --write frontend/src/routes/components/SkillSheetCreator.svelte frontend/src/lib/utils/reportDiff.js frontend/src/lib/utils/reportDiff.spec.js frontend/src/app.css` and re-run lint.

- [ ] **Step 4: Manual end-to-end smoke test**

Start the dev server and walk through Phase 2 end-to-end:

```bash
cd frontend && bun run dev
```

Checklist:
1. Open SkillSheet creator, paste 3 example reports of the same scan type, click Analyse.
2. **Empty state:** before generating, verify the right panel shows the page-outline placeholder.
3. **Pill captions:** verify the Style pill shows a truncated caption from the summary.
4. Answer some questions, skip others. Verify the Questions pill caption updates as expected.
5. Go to Test stage. Verify the Test pill caption is empty (no caption until first generation).
6. Click Generate. Verify the report renders with NO badge and NO flash (first generation).
7. Verify the Test pill caption now shows the first line of `testFindings` (truncated to 40 chars).
8. Go to Refine. Add a refine rule like "always include lesion size in mm". Click Regenerate.
9. **Diff flash:** verify the changed sections of the report get a purple left-border flash that fades over ~1.2s.
10. **Diff badge:** verify a small badge appears in the header reading e.g. `1 section changed` or `2 sections changed`.
11. Click the badge — verify it scrolls to the first flashed block.
12. Regenerate without making any changes. Verify the badge reads `no changes`.
13. Add a sweeping rule that should change most of the report. Verify the badge reads `regenerated`.
14. Verify the Refine pill caption reads `N rules added`.
15. Save the template via the bottom bar — verify the existing save flow still works end-to-end.

- [ ] **Step 5: Commit any formatting fixes**

If `bun run lint` produced formatting fixes that needed to be applied in step 3:

```bash
git add -u
git commit -m "style(frontend): apply prettier formatting"
```

Otherwise skip.

---

## Spec coverage check

| Spec section                                  | Implementing task                       |
|-----------------------------------------------|-----------------------------------------|
| Condensed-summary captions on stage pills     | Task 4                                  |
| Page-outline empty state                      | Task 5                                  |
| Per-block diff flash on regenerate            | Tasks 1 + 2                             |
| Diff badge in preview header                  | Task 3                                  |
| Per-block render restructure                  | Task 2                                  |
| Block split helper (`splitIntoBlocks`)        | Task 1                                  |
| Block-level diff with badge logic             | Task 1                                  |
| First-generation no-badge edge case           | Task 1 (test) + Task 2 (state)          |
| `no changes` badge                            | Task 1 (test) + Task 3 (UI)             |
| `regenerated` badge for >70% changed          | Task 1 (test) + Task 3 (UI)             |
| Stable Svelte each-key for blocks             | Task 1 (`hash` + `id` field)            |
| Flash CSS animation                           | Task 2 (`@keyframes diff-flash`)        |
| Click-to-scroll on badge                      | Task 3 (`scrollToFirstFlash`)           |
| No new dependencies                           | Confirmed — only `diffReports` added    |
| No backend changes                            | Confirmed — no API surface touched      |
| Phase 1 untouched                             | Confirmed — no edits above line 240     |
