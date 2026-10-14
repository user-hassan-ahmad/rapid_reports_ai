<script lang="ts">
	/**
	 * An opened pack card's body (the simplified card, Hassan 2026-10-13: "No further imaging" four times on one
	 * screen, and a Calculate button implied the top result could be stale). Top to bottom:
	 * 1. (the head, in PackCard: guideline · result pill · assumptions chip);
	 * 2. the values: every input, editable, with its provenance badge; assumed first, then pre-filled, then read,
	 *    then answered or changed, then still open; N/A hidden behind "+N not applicable";
	 * 3. the result, ONCE and live: the draft outcome, re-previewed after each edit (no separate Calculate result):
	 *    the headline, then only the recommendation text the action (in the pill) does not already say, then the
	 *    classification clamped to two lines; with no outcome yet, the most likely outcome and what decides it;
	 * 4. notes and source, collapsed.
	 * A card that does not apply leads with the specific reason; its values wait behind "values". `compact` (a
	 * side-by-side sibling column) keeps the values and the result only. Apply is never offered.
	 */
	import type { OpenResult } from '../types';
	import Icon, { type IconName } from './Icon.svelte';
	import {
		allValueRows,
		assumptionsOf,
		categoryColor,
		categoryText,
		decidingQuestion,
		notNeededRows,
		openQuestions,
		recommendationBeyond,
		scopeDoubts,
		shownValue,
		sourcesOf,
		verdictOf,
		type Verdict
	} from './format';
	import Reference from './Reference.svelte';
	import ValueRow from './ValueRow.svelte';
	import ValueEdit from './ValueEdit.svelte';

	let {
		result,
		compact = false,
		assumptions = null,
		verdict = undefined,
		onEdit = null,
		busy = false,
		editError = null,
		guideline = ''
	}: {
		result: OpenResult;
		compact?: boolean;
		/** The assumed eligibility checks; null derives them (assumptionsOf). */
		assumptions?: string[] | null;
		/** The verdict the head shows; derived from the preview when not given. */
		verdict?: Verdict | null;
		/** Answer or change a value (the card re-previews and the result follows). Absent: read-only. */
		onEdit?: ((input: string, value: string) => void) | null;
		/** The card is re-previewing after an edit: the result shown is about to update. */
		busy?: boolean;
		editError?: string | null;
		/** The guideline's name, for the applicability warning. */
		guideline?: string;
	} = $props();
	let doubtEditing = $state<string | null>(null);

	const p = $derived(result.preview);
	const v = $derived(verdict === undefined ? verdictOf(p) : verdict);
	const rows = $derived(allValueRows(result));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	// a pre-Task 3 preview has no draft: its open questions are not in the value list
	const questions = $derived(p && !p.draft?.length ? openQuestions(p) : []);
	const src = $derived(sourcesOf(v?.citations ?? []));
	const decided = $derived(!!v && v.category !== 'open' && !v.tentative);
	const longText = $derived(!!v && v.classification.length > 110);
	// an exclusion worded by its outcome (§7.12 item 1) says what to do instead; a generic one has no action
	const recText = $derived(v ? (v.excluded ? v.action : recommendationBeyond(v.action, v.recommendation)) : '');
	// asked inputs that cannot change the outcome wait behind "N not needed on this branch" (§7.12 item 3)
	// (a card that does not apply keeps them in its values list: nothing there can change the outcome)
	const notNeededIds = $derived(new Set(v?.excluded ? [] : notNeededRows(p).map((r) => r.input)));
	const notNeededList = $derived(rows.filter((r) => notNeededIds.has(r.input)));
	let showNotNeeded = $state(false);
	const shownRows = $derived(rows.filter((r) => r.state !== 'not_applicable' && !notNeededIds.has(r.input)));
	const naRows = $derived(rows.filter((r) => r.state === 'not_applicable'));
	let showNa = $state(false);
	let showValues = $state(false);
	let showMore = $state(false);
	let showNotes = $state(false);
	let showSource = $state(false);
	let showPossible = $state(false);
	let openNote = $state<number | null>(null);
	const uid = $props.id(); // ids for aria-controls / aria-describedby
	const icon: Record<string, IconName> = { none: 'check', surveillance: 'clock', workup: 'search', refer: 'alert', info: 'info', not_applicable: 'info', neutral: 'dot', open: 'open' };
	const likely = $derived(p?.most_likely ?? null);
	const branches = $derived((p?.deciding ?? []).slice(0, 3));
	const decidingQ = $derived(p ? decidingQuestion(p) : '');
	const underAssumptions = $derived(assumed.length > 0 || !!p?.assumed_eligible);
	// pre-filled values that would make the guideline not apply: never silent (Hassan's rule), shown first
	const doubts = $derived(scopeDoubts(p));
	const doubtIds = $derived(new Set(doubts.map((d) => d.input)));
</script>

<div class="cp-pack-body" class:cp-compact={compact}>
	{#if !p}
		{#if result.entry?.content.summary}<p class="cp-p">{result.entry.content.summary}</p>{/if}
	{:else}
		{#if editError}<p class="cp-p cp-edit-error" role="alert">{editError}</p>{/if}
		{#each doubts as d (d.input)}
			<div class="cp-doubt" role="note" data-testid="cp-scope-doubt">
				<p class="cp-p">
					<Icon name="warn" size={13} />
					<span><b>{d.label}: {shownValue(d.value)}</b> (pre-filled) would make {guideline || 'this guideline'} not apply — confirm or change it</span>
				</p>
				{#if onEdit}
					<div class="cp-doubt-actions">
						{#if doubtEditing === d.input}
							<ValueEdit
								label={d.label}
								value={d.value}
								options={d.options}
								onSave={(val) => {
									doubtEditing = null;
									onEdit?.(d.input, val);
								}}
								onCancel={() => (doubtEditing = null)}
							/>
						{:else}
							<!-- confirming sends the value back as the radiologist's answer: only then can it exclude -->
							{#if d.value}<button type="button" class="rv-btn" aria-label={`Confirm ${d.label} ${shownValue(d.value)}`} onclick={() => onEdit?.(d.input, d.value)}>Confirm</button>{/if}
							<button type="button" class="rv-btn" aria-label={`Change ${d.label}`} onclick={() => (doubtEditing = d.input)}>Change</button>
						{/if}
					</div>
				{/if}
			</div>
		{/each}
		<!-- 2. the values -->
		{#if rows.length}
			<section class="cp-values" aria-label="Values">
				{#if v?.excluded}
					<!-- a card that does not apply keeps its values out of the way -->
					<button type="button" class="cp-link cp-aux-toggle" aria-expanded={showValues} aria-controls="{uid}-values" onclick={() => (showValues = !showValues)}
						>values <span class="cp-caret"><Icon name="chev" size={11} /></span></button
					>
				{:else}
					<div class="cp-label">Values</div>
				{/if}
				<ul class="cp-val-list" id="{uid}-values" hidden={!!v?.excluded && !showValues}>
					{#each shownRows as r (r.input)}
						<ValueRow row={r} {uid} {onEdit} doubt={doubtIds.has(r.input)} />
					{/each}
					{#if naRows.length}
						{#if showNa}
							{#each naRows as r (r.input)}<ValueRow row={r} {uid} {onEdit} />{/each}
						{/if}
						<li class="cp-na-toggle">
							<button type="button" class="cp-link cp-aux-toggle" aria-expanded={showNa} onclick={() => (showNa = !showNa)}
								>{showNa ? 'hide not applicable' : `+${naRows.length} not applicable`}</button
							>
						</li>
					{/if}
				</ul>
			</section>
		{/if}
		{#if notNeededList.length && !v?.excluded}
			<section class="cp-not-needed" aria-label="Not needed on this branch">
				<button type="button" class="cp-link cp-aux-toggle" aria-expanded={showNotNeeded} aria-controls="{uid}-not-needed" onclick={() => (showNotNeeded = !showNotNeeded)}
					>{notNeededList.length} not needed on this branch <span class="cp-caret"><Icon name="chev" size={11} /></span></button
				>
				<ul class="cp-val-list" id="{uid}-not-needed" hidden={!showNotNeeded}>
					{#each notNeededList as r (r.input)}<ValueRow row={r} {uid} {onEdit} />{/each}
				</ul>
			</section>
		{/if}
		{#if questions.length && p.state !== 'does_not_apply'}
			<section class="cp-open-q" aria-label="Still open">
				<div class="cp-label">Still open</div>
				<ul class="cp-open-list">
					{#each questions as q, i (i)}<li>{q}</li>{/each}
				</ul>
			</section>
		{/if}

		<!-- 3. the result, once and live -->
		{#if decided && v}
			<section
				class="cp-verdict"
				style:--cp-cat={categoryColor(v.category)}
				style:--cp-cat-text={categoryText(v.category)}
				data-cat={v.category}
				data-testid={v.excluded ? 'cp-exclusion' : undefined}
				aria-label="Verdict"
				aria-busy={busy}
			>
				<p class="cp-p cp-headline">{v.headline}</p>
				<!-- the action is in the pill; here only what the recommendation adds to it (later steps, conditions) -->
				{#if recText}<p class="cp-p cp-recommendation">{recText}</p>{/if}
				{#if v.excluded && v.classification && v.classification !== v.headline}
					<!-- does not apply: the specific reason leads; the generic exclusion text waits behind "full reason" -->
					<button type="button" class="cp-link cp-more" aria-expanded={showMore} aria-controls="{uid}-cls" onclick={() => (showMore = !showMore)}
						>{showMore ? 'hide full reason' : 'full reason'}</button
					>
					<p class="cp-p cp-classification" id="{uid}-cls" hidden={!showMore}>{v.classification}</p>
				{:else if v.classification && v.classification !== v.headline}
					<p class="cp-p cp-classification" class:cp-clamp={longText && !showMore && !compact} id="{uid}-cls">{v.classification}</p>
					{#if longText && !compact}
						<button type="button" class="cp-link cp-more" aria-expanded={showMore} aria-controls="{uid}-cls" onclick={() => (showMore = !showMore)}
							>{showMore ? 'less' : 'more'}</button
						>
					{/if}
				{/if}
				<p class="cp-p cp-onvalues" aria-live="polite">{busy ? 'Updating on the new values…' : 'On these values'}</p>
			</section>
		{/if}
		{#if v?.ifApplies}
			<!-- a scope doubt leads the card; the drafted outcome stays, secondary (controller ruling 2026-10-14) -->
			<p class="cp-p cp-if-applies" data-testid="cp-if-applies">{v.ifApplies}</p>
		{/if}
		{#if !decided && !v?.ifApplies && (likely || (branches.length && decidingQ))}
			<!-- no outcome yet: the likeliest one when there is one, and what genuinely decides it (max three branches);
			     the full list stays behind "show all" -->
			<section class="cp-likely" aria-label={likely ? 'Most likely' : 'What decides it'}>
				{#if likely}
				<p class="cp-p cp-likely-line" style:--cp-cat={categoryColor(likely.category || 'neutral')} style:--cp-cat-text={categoryText(likely.category || 'neutral')}>
					<Icon name={icon[likely.category || 'neutral']} size={13} />
					<span>Most likely: <b>{likely.headline}</b></span>
					{#if underAssumptions}<span class="cp-chip cp-chip-warn">⚠ under assumptions</span>{/if}
				</p>
				{/if}
				{#if branches.length && decidingQ}
					<div class="cp-depends">
						<p class="cp-p">Depends on {decidingQ}</p>
						<ul class="cp-branches">
							{#each branches as b, i (i)}
								<li style:--cp-cat-text={categoryText(b.category || 'neutral')}>
									<span class="cp-branch-answer">{b.answer}</span><span class="cp-muted" aria-hidden="true">→</span><span class="cp-sr-only">:</span>
									<b>{b.headline}</b>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if p.possible.length > 1}
					<button type="button" class="cp-link cp-possible-toggle" aria-expanded={showPossible} aria-controls="{uid}-possible" onclick={() => (showPossible = !showPossible)}
						>{showPossible ? 'hide all' : `show all ${p.possible.length}`}</button
					>
					<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
						{#each p.possible as o, i (i)}<li>{o}</li>{/each}
					</ul>
				{/if}
			</section>
		{:else if !decided && p.state !== 'does_not_apply' && p.possible.length === 1}
			<section>
				<div class="cp-label">Possible</div>
				<p class="cp-p">{p.possible[0]}</p>
			</section>
		{:else if !decided && p.state !== 'does_not_apply' && p.possible.length > 1}
			<section class="cp-possible">
				<button type="button" class="cp-link cp-possible-toggle" aria-expanded={showPossible} aria-controls="{uid}-possible" onclick={() => (showPossible = !showPossible)}
					>{p.possible.length} outcomes still possible — {showPossible ? 'hide' : 'show'}</button
				>
				<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
					{#each p.possible as o, i (i)}<li>{o}</li>{/each}
				</ul>
			</section>
		{/if}

		<!-- 4. notes and source, collapsed -->
		{#if decided && v && !compact && (v.caveats.length || src.short)}
			<div class="cp-aux">
				{#if v.caveats.length}
					<div class="cp-notes">
						<button type="button" class="cp-link cp-aux-toggle" aria-expanded={showNotes} aria-controls="{uid}-notes" onclick={() => (showNotes = !showNotes)}
							>{v.caveats.length} {v.caveats.length === 1 ? 'note' : 'notes'} <span class="cp-caret"><Icon name="chev" size={11} /></span></button
						>
						<ul class="cp-note-list" id="{uid}-notes" hidden={!showNotes}>
							{#each v.caveats as c, i (i)}
								<li>
									<button type="button" class="cp-note" class:cp-note--open={openNote === i} aria-expanded={openNote === i} onclick={() => (openNote = openNote === i ? null : i)}
										>{c}</button
									>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
				{#if src.short}
					<div class="cp-source">
						<button type="button" class="cp-link cp-aux-toggle" aria-expanded={showSource} aria-controls="{uid}-src" onclick={() => (showSource = !showSource)}
							>{src.short}{#if src.more}<span class="cp-muted cp-src-more">+{src.more}</span>{/if}
							<span class="cp-caret"><Icon name="chev" size={11} /></span></button
						>
						<ul class="cp-src-list" id="{uid}-src" hidden={!showSource}>
							{#each src.full as s, i (i)}<li>{s}</li>{/each}
						</ul>
					</div>
				{/if}
			</div>
		{/if}
		{#if p.degraded}
			<p class="cp-p cp-muted cp-degraded">Some values could not be checked</p>
		{/if}
	{/if}
	{#if !compact && result.reference}
		<Reference reference={result.reference} />
	{/if}
</div>

<style>
	.cp-pack-body {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}
	.cp-pack-body section {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.cp-p {
		margin: 0;
	}

	/* ── 1. the verdict: the one loud thing on the card ── */
	.cp-verdict {
		gap: 4px;
	}
	.cp-headline {
		font-size: 1.0625rem;
		font-weight: 650;
		line-height: 1.3;
		letter-spacing: -0.01em;
		color: var(--rv-text);
	}
	/* a collapsed list stays collapsed wherever the body renders (cards.css covers it only inside the rail list) */
	.cp-val-list[hidden] {
		display: none;
	}
	.cp-not-needed {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.75rem;
	}
	.cp-if-applies {
		font-size: 0.8125rem;
		line-height: 1.45;
		color: var(--rv-muted);
	}
	.cp-na-toggle {
		list-style: none;
		margin-top: 2px;
		font-size: 0.75rem;
	}
	.cp-recommendation {
		font-size: 0.875rem;
		line-height: 1.45;
		color: var(--rv-text);
	}
	.cp-classification {
		margin-top: 2px;
		font-size: 0.8125rem;
		line-height: 1.45;
		color: var(--rv-muted);
	}
	.cp-clamp {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.cp-more {
		align-self: flex-start;
		font-size: 0.75rem;
	}
	.cp-onvalues {
		font-size: 0.6875rem;
		color: var(--rv-muted);
		opacity: 0.85;
	}

	/* ── 2–3. notes and source: two quiet lines ── */
	.cp-aux {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.8125rem;
	}
	.cp-aux-toggle {
		align-self: flex-start;
		text-align: left;
		color: var(--rv-muted);
		text-decoration: none;
	}
	.cp-caret {
		display: inline-block;
		margin-left: 2px;
		transition: transform 0.15s;
	}
	.cp-aux-toggle[aria-expanded='true'] .cp-caret {
		transform: rotate(90deg);
	}
	.cp-src-more {
		margin-left: 6px;
	}
	@media (prefers-reduced-motion: reduce) {
		.cp-caret {
			transition: none;
		}
	}
	.cp-aux-toggle:hover {
		color: var(--rv-text);
	}
	.cp-aux-toggle[aria-expanded='true'] {
		color: var(--rv-text);
	}
	.cp-note-list,
	.cp-src-list {
		max-height: 16rem;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin: 4px 0 2px;
		padding-left: 14px;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.cp-src-list {
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.cp-note {
		display: -webkit-box;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		-webkit-box-orient: vertical;
		overflow: hidden;
		width: 100%;
		padding: 0;
		font: inherit;
		font-size: 0.8125rem;
		line-height: 1.45;
		text-align: left;
		color: var(--rv-text);
		background: none;
		border: 0;
		cursor: pointer;
	}
	.cp-note--open {
		display: block;
		-webkit-line-clamp: unset;
		line-clamp: unset;
	}

	/* ── 4. values: lighter than the verdict ── */
	.cp-values {
		padding-top: 10px;
		border-top: 1px solid var(--rv-border);
		font-size: 0.8125rem;
	}
	.cp-val-list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.cp-open-q {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-open-list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.cp-open-list li {
		padding: 1px 7px;
		border-radius: 5px;
		border: 1px dashed var(--rv-border-strong);
	}
	.cp-likely-line {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 6px;
		font-size: 0.875rem;
		color: var(--cp-cat-text);
	}
	.cp-likely-line :global(.cp-icon) {
		color: var(--cp-cat);
	}
	.cp-likely-line b {
		font-weight: 650;
	}
	.cp-depends {
		font-size: 0.8125rem;
		color: var(--rv-muted);
		line-height: 1.5;
	}
	.cp-branches {
		margin: 2px 0 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.cp-branches li {
		display: flex;
		gap: 6px;
		align-items: baseline;
	}
	.cp-branch-answer {
		min-width: 6.5em;
	}
	.cp-branches b {
		font-weight: 600;
		color: var(--cp-cat-text);
	}
	.cp-values:first-child {
		padding-top: 0;
		border-top: 0;
	}
	/* the result follows the values under a rule */
	.cp-values + .cp-verdict,
	.cp-values + .cp-likely,
	.cp-open-q + .cp-verdict {
		padding-top: 10px;
		border-top: 1px solid var(--rv-border);
	}
	.cp-doubt {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 10px;
		border-radius: 8px;
		border: 1px solid color-mix(in srgb, var(--rv-amber-line) 55%, transparent);
		background: var(--rv-amber-bg);
		color: var(--rv-text);
		font-size: 0.8125rem;
	}
	.cp-doubt p {
		display: flex;
		gap: 6px;
		align-items: flex-start;
	}
	.cp-doubt p :global(.cp-icon) {
		color: var(--rv-amber-text);
		margin-top: 2px;
	}
	.cp-doubt-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.cp-edit-error {
		font-size: 0.8125rem;
		color: var(--rv-red-text);
	}
	.cp-possible-toggle {
		align-self: flex-start;
		text-align: left;
	}
	.cp-possible-toggle {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-possible-list {
		margin-top: 4px;
		font-size: 0.8125rem;
	}
	.cp-compact {
		font-size: 0.8125rem;
	}
	.cp-compact .cp-headline {
		font-size: 0.9375rem;
	}
	.cp-degraded {
		font-size: 0.8125rem;
		font-style: italic;
	}
</style>
