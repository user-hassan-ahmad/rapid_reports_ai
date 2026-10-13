<script lang="ts">
	/**
	 * The §5.3 quiet exam card: one line, "<name> · <outcome>", with a chevron that expands the full (read-only)
	 * body below it. Never shows optional inputs or Apply. The exam card is auto-previewed, so expanding needs no
	 * request and stays local to the line.
	 */
	import { outcomeOf } from '../state';
	import type { Card, OpenResult } from '../types';
	import { setByExam } from './format';
	import PackBody from './PackBody.svelte';

	let { card, result }: { card: Card; result: OpenResult } = $props();
	let expanded = $state(false);
	const p = $derived(result.preview);
	const line = $derived(`${card.name} · ${outcomeOf(p)?.classification ?? ''}`);
</script>

<div class="cp-quiet" data-testid="cp-quiet">
	<button type="button" class="cp-quiet-line" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
		<span class="cp-quiet-text">{line}</span>
		{#if setByExam(p)}<span class="cp-chip">set by the exam</span>{/if}
		<svg class="cp-quiet-chev" class:open={expanded} width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
	</button>
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
	.cp-quiet-line {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
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
