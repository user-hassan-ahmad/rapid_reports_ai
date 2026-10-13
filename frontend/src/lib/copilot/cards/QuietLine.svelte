<script lang="ts">
	/**
	 * The §5.3 quiet exam card: one line, "<name> · <outcome>", with a chevron that expands the full (read-only)
	 * body below it. Never shows optional inputs or Apply. The exam card is auto-previewed, so expanding needs no
	 * request and stays local to the line.
	 * A normal outcome that rests on assumed eligibility checks stays one line, but never without a cue (ruling
	 * 2026-10-13): a "⚠ N checks assumed" button beside it expands the assumed list (aria-expanded/aria-controls).
	 */
	import { outcomeOf } from '../state';
	import type { Card, OpenResult } from '../types';
	import { assumptionsOf, setByExam } from './format';
	import PackBody from './PackBody.svelte';

	let { card, result }: { card: Card; result: OpenResult } = $props();
	let expanded = $state(false);
	const p = $derived(result.preview);
	const line = $derived(`${card.name} · ${outcomeOf(p)?.classification ?? ''}`);
	const assumed = $derived(assumptionsOf(p));
	const warn = $derived(assumed.length > 0 || !!p?.assumed_eligible);
	let showAssumed = $state(false);
	const uid = $props.id();
</script>

<div class="cp-quiet" class:cp-quiet--warn={warn} data-testid="cp-quiet">
	<div class="cp-quiet-row">
		<button type="button" class="cp-quiet-line" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
			<span class="cp-quiet-text">{line}</span>
			{#if setByExam(p)}<span class="cp-chip">set by the exam</span>{/if}
			<svg class="cp-quiet-chev" class:open={expanded} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
		</button>
		{#if warn}
			<button
				type="button"
				class="cp-chip cp-chip-warn cp-quiet-warn"
				aria-expanded={showAssumed}
				aria-controls="{uid}-assumed"
				onclick={() => (showAssumed = !showAssumed)}
				>⚠ {assumed.length ? `${assumed.length} ${assumed.length === 1 ? 'check' : 'checks'}` : 'checks'} assumed<span class="cp-sr-only"
					>{assumed.length ? `: ${assumed.join('; ')}` : ''}</span
				></button
			>
		{/if}
	</div>
	{#if warn}
		<ul class="cp-list cp-quiet-assumed" id="{uid}-assumed" hidden={!showAssumed}>
			{#each assumed.length ? assumed : ['Eligibility checks were assumed (not listed)'] as a, i (i)}<li>{a}</li>{/each}
		</ul>
	{/if}
	{#if expanded}
		<div class="cp-quiet-body"><PackBody {result} /></div>
	{/if}
</div>

<style>
	.cp-quiet {
		border-left: 3px solid var(--rv-green-line);
		border-radius: 6px;
		background: var(--rv-surface);
	}
	.cp-quiet-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding-right: 8px;
	}
	.cp-quiet-warn {
		font: inherit;
		font-size: 10.5px;
		font-weight: 600;
		cursor: pointer;
	}
	.cp-quiet--warn {
		border-left-color: var(--rv-amber-line);
	}
	.cp-quiet-assumed {
		margin: 0 12px 8px;
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-quiet-line {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		font: inherit;
		font-size: 0.8125rem;
		text-align: left;
		color: var(--rv-muted);
		background: none;
		border: 0;
		cursor: pointer;
	}
	.cp-quiet-line:hover {
		color: var(--rv-text);
	}
	.cp-quiet-text {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-quiet-chev {
		flex-shrink: 0;
		transition: transform 0.2s;
	}
	.cp-quiet-chev.open {
		transform: rotate(180deg);
	}
	.cp-quiet-body {
		padding: 6px 12px 12px;
		border-top: 1px solid var(--rv-border);
	}
</style>
