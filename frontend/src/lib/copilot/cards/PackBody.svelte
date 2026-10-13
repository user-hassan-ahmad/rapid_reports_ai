<script lang="ts">
	/**
	 * An opened pack card's body, read-only, judgement first (B-design, Hassan after checkpoint 3: the verdict was
	 * buried under the classification, five caveats and four repeated citations):
	 * 1. the verdict: a short headline, the action as one bold line with its category icon, then the full
	 *    classification in normal weight, clamped to two lines with "more";
	 * 2. notes (the caveats), collapsed to "N notes"; each opens to one line, then in full on click;
	 * 3. the source as ONE short line ("ESE 2023 · Fig 5, p. 18"), identical citations merged, the full list on
	 *    request;
	 * 4. the values (ValueRow), lighter than the verdict, then "Still open" as a compact list.
	 * With no outcome yet: "Still open" and one collapsed "N outcomes still possible" line. The assumed checks sit
	 * last, collapsed (their cue is in the head). `compact` (a side-by-side sibling column) keeps the verdict and the
	 * values only. No inputs, Calculate or Apply.
	 */
	import type { OpenResult } from '../types';
	import Icon, { type IconName } from './Icon.svelte';
	import { assumptionsOf, categoryColor, decidingQuestion, openQuestions, sourcesOf, valueRows, verdictOf, type Verdict } from './format';
	import Reference from './Reference.svelte';
	import ValueRow from './ValueRow.svelte';

	let {
		result,
		compact = false,
		assumptions = null,
		verdict = undefined
	}: {
		result: OpenResult;
		compact?: boolean;
		/** The assumed eligibility checks; null derives them (assumptionsOf). */
		assumptions?: string[] | null;
		/** The verdict the head shows; derived from the preview when not given. */
		verdict?: Verdict | null;
	} = $props();
	const p = $derived(result.preview);
	const v = $derived(verdict === undefined ? verdictOf(p) : verdict);
	const rows = $derived(valueRows(result));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	const questions = $derived(p ? openQuestions(p) : []);
	const src = $derived(sourcesOf(v?.citations ?? []));
	const decided = $derived(!!v && v.category !== 'open' && !v.tentative);
	const longText = $derived(!!v && v.classification.length > 110);
	let showMore = $state(false);
	let showNotes = $state(false);
	let showSource = $state(false);
	let showAssumed = $state(false);
	let showPossible = $state(false);
	let openNote = $state<number | null>(null);
	const uid = $props.id(); // ids for aria-controls / aria-describedby
	const icon: Record<string, IconName> = { none: 'check', surveillance: 'clock', workup: 'search', refer: 'alert', info: 'info', not_applicable: 'slash', neutral: 'dot', open: 'open' };
	const likely = $derived(p?.most_likely ?? null);
	const branches = $derived((p?.deciding ?? []).slice(0, 3));
	const decidingQ = $derived(p ? decidingQuestion(p) : '');
	const underAssumptions = $derived(assumed.length > 0 || !!p?.assumed_eligible);
</script>

<div class="cp-pack-body" class:cp-compact={compact}>
	{#if !p}
		{#if result.entry?.content.summary}<p class="cp-p">{result.entry.content.summary}</p>{/if}
	{:else}
		{#if decided && v}
			<section class="cp-verdict" style:--cp-cat={categoryColor(v.category)} data-cat={v.category} data-testid={v.category === 'not_applicable' ? 'cp-exclusion' : undefined} aria-label="Verdict">
				<p class="cp-p cp-headline">{v.headline}</p>
				{#if v.category === 'not_applicable'}
					<p class="cp-p cp-action"><Icon name="slash" size={14} /> Does not apply</p>
				{:else if v.action}
					<p class="cp-p cp-action"><Icon name={icon[v.category]} size={14} /> {v.action}</p>
				{/if}
				{#if v.classification && v.classification !== v.headline}
					<p
						class="cp-p cp-classification"
						class:cp-clamp={longText && !showMore && !compact}
						id="{uid}-cls"
					>
						{v.classification}
					</p>
					{#if longText && !compact}
						<button type="button" class="cp-link cp-more" aria-expanded={showMore} aria-controls="{uid}-cls" onclick={() => (showMore = !showMore)}
							>{showMore ? 'less' : 'more'}</button
						>
					{/if}
				{/if}
				<p class="cp-p cp-onvalues">On these values</p>
			</section>
			{#if !compact && (v.caveats.length || src.short)}
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
		{/if}
			{#if !decided && likely}
				<!-- the backend's likeliest outcome, and what genuinely decides it (max three branches); the full list stays
				     behind "show all" -->
				<section class="cp-likely" aria-label="Most likely">
					<p class="cp-p cp-likely-line" style:--cp-cat={categoryColor(likely.category ?? 'neutral')}>
						<Icon name={icon[likely.category ?? 'neutral']} size={13} />
						<span>Most likely: <b>{likely.headline}</b></span>
						{#if underAssumptions}<span class="cp-chip cp-chip-warn">⚠ under assumptions</span>{/if}
					</p>
					{#if branches.length && decidingQ}
						<div class="cp-depends">
							<p class="cp-p">Depends on {decidingQ}</p>
							<ul class="cp-branches">
								{#each branches as b, i (i)}
									<li style:--cp-cat={categoryColor(b.category ?? 'neutral')}>
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
			{/if}
		{#if rows.length}
			<section class="cp-values" aria-label="Values">
				<div class="cp-label">Values</div>
				<ul class="cp-val-list">
					{#each rows as r (r.input)}
						<ValueRow row={r} {uid} />
					{/each}
				</ul>
			</section>
		{/if}
		{#if p.state !== 'does_not_apply'}
			{#if questions.length}
				<section class="cp-open-q" aria-label="Still open">
					<div class="cp-label">Still open</div>
					<ul class="cp-open-list">
						{#each questions as q, i (i)}<li>{q}</li>{/each}
					</ul>
				</section>
			{/if}
			{#if !decided && !likely && p.possible.length === 1}
				<section>
					<div class="cp-label">Possible</div>
					<p class="cp-p">{p.possible[0]}</p>
				</section>
			{:else if !decided && !likely && p.possible.length > 1}
				<section class="cp-possible">
					<button
						type="button"
						class="cp-link cp-possible-toggle"
						aria-expanded={showPossible}
						aria-controls="{uid}-possible"
						onclick={() => (showPossible = !showPossible)}
						>{p.possible.length} outcomes still possible — {showPossible ? 'hide' : 'show'}</button
					>
					<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
						{#each p.possible as o, i (i)}<li>{o}</li>{/each}
					</ul>
				</section>
			{/if}
		{/if}
		{#if assumed.length && !compact}
			<div class="cp-assumed">
				<button
					type="button"
					class="cp-link cp-assumed-toggle"
					aria-expanded={showAssumed}
					aria-controls="{uid}-assumed"
					onclick={() => (showAssumed = !showAssumed)}
					><Icon name="warn" size={12} /> Assumed eligible: {assumed.length} {assumed.length === 1 ? 'check' : 'checks'}</button
				>
				<ul class="cp-list cp-assumed-list" id="{uid}-assumed" hidden={!showAssumed}>
					{#each assumed as a, i (i)}<li>{a}</li>{/each}
				</ul>
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
	.cp-verdict[data-cat='neutral'] .cp-action {
		color: var(--rv-text);
	}
	.cp-action {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 0.875rem;
		font-weight: 650;
		color: var(--cp-cat);
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
		color: var(--cp-cat);
	}
	.cp-values:first-child {
		padding-top: 0;
		border-top: 0;
	}
	.cp-possible-toggle,
	.cp-assumed-toggle {
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
	.cp-assumed-toggle {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 0.8125rem;
		color: var(--rv-amber-line);
		text-decoration: none;
	}
	.cp-assumed-list {
		margin-top: 4px;
		font-size: 0.8125rem;
		color: var(--rv-muted);
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
