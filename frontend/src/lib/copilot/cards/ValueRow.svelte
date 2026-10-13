<script lang="ts">
	/**
	 * One value the card shows (Slice B1, §7.5), read-only until B2:
	 * - read: plain;
	 * - prefilled: the value on the agreed amber-soft highlight (the value only, never the row), plus a "pre-filled"
	 *   chip whose reasons (why[]) are in its tooltip and in the row's description;
	 * - an exam preset (by === 'exam'): the neutral "set by the exam" chip, no highlight (unless it also carries a
	 *   real reason: then both chips, the highlight and the reason);
	 * - answered / edited: as set; not_applicable: "N/A".
	 * A row with a quote or reasons is focusable (keyboard, or a tap) and shows them in a bubble; screen readers get
	 * them as its description.
	 */
	import { WHY_EXAM, type ValueRow } from './format';

	let { row, uid }: { row: ValueRow; uid: string } = $props();
	const why = $derived(row.why.filter((w) => w !== WHY_EXAM));
	const prefilled = $derived(row.state === 'prefilled' && (!row.byExam || why.length > 0));
	const reasons = $derived(why.length ? why.join('; ') : 'not read with certainty');
	// every pre-filled row is focusable, so its reasons are reachable without hover
	const described = $derived(!!row.quote || prefilled);
	const descId = $derived(`${uid}-d-${row.input}`);
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<li
	class="cp-val"
	data-state={row.state}
	tabindex={described ? 0 : undefined}
	aria-describedby={described ? descId : undefined}
>
	<span class="cp-val-label">{row.label}</span>
	<span class="cp-val-value">
		{#if row.state === 'not_applicable'}
			<span class="cp-muted">N/A</span>
		{:else if prefilled}
			<b class="cp-prefill">{row.value}</b>
		{:else if row.value}
			<b>{row.value}</b>
		{:else}
			<span class="cp-muted">{row.state.replace(/_/g, ' ')}</span>
		{/if}
		{#if row.byExam}
			<span class="cp-chip cp-val-chip">set by the exam</span>
		{/if}
		{#if prefilled}
			<!-- no native title: the row's own bubble shows the reasons (a title showed them twice, Hassan 2026-10-13) -->
			<span class="cp-chip cp-val-chip cp-chip-why">pre-filled</span>
		{/if}
	</span>
	{#if described}
		<span class="cp-quote" id={descId}>
			{#if row.quote}<span class="cp-quote-text">“{row.quote}”</span>{/if}
			{#if prefilled}<span class="cp-why">Pre-filled: {reasons}</span>{/if}
		</span>
	{/if}
</li>

<style>
	.cp-val {
		position: relative;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
		padding: 2px 6px;
		margin: 0 -6px;
		border-radius: 4px;
	}
	.cp-val[tabindex]:hover,
	.cp-val[tabindex]:focus {
		background: var(--rv-surface-hover);
		outline: none;
	}
	.cp-val[tabindex]:focus-visible {
		box-shadow: 0 0 0 2px var(--rv-focus);
	}
	.cp-val-label {
		flex: 0 0 44%; /* one column of labels, long ones wrap */
		color: var(--rv-muted);
	}
	.cp-val-value {
		flex: 1;
		min-width: 0;
		font-variant-numeric: tabular-nums;
	}
	.cp-val-value b {
		font-weight: 600;
	}
	/* the agreed amber-soft highlight, on the value only */
	.cp-prefill {
		padding: 0 4px;
		border-radius: 3px;
		background: var(--rv-amber-bg);
	}
	.cp-val-chip {
		display: inline-block;
		margin-left: 6px;
		vertical-align: 1px;
	}
	.cp-chip-why {
		cursor: help;
	}
	/* a bubble under the row, out of the flow: revealing it never moves what is below (or under the pointer) */
	.cp-quote {
		display: none;
		position: absolute;
		left: 0;
		right: 0;
		top: 100%;
		z-index: 5;
		margin-top: 2px;
		padding: 5px 8px;
		border-radius: 6px;
		border: 1px solid var(--rv-border-strong);
		background: var(--rv-overlay);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
		font-size: 0.8125rem;
		color: var(--rv-text);
		pointer-events: none;
	}
	.cp-quote-text {
		display: block;
		font-style: italic;
	}
	.cp-why {
		display: block;
		color: var(--rv-amber-line);
	}
	.cp-val:hover .cp-quote,
	.cp-val:focus .cp-quote {
		display: block;
	}
	:global(.cp-compact) .cp-val-label {
		flex-basis: 100%;
	}
</style>
