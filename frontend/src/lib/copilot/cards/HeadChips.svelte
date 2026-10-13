<script lang="ts">
	/** The head's second line: the key values as compact chips (read solid, pre-filled amber outline with a dot,
	 *  assumed dashed, exam-set neutral with a small icon), then the assumed-checks cue at the right. */
	import type { OpenResult } from '../types';
	import AssumedChip from './AssumedChip.svelte';
	import Icon from './Icon.svelte';
	import { headChips } from './format';

	let { result, assumed, checkFirst = false }: { result: OpenResult; assumed: string[]; checkFirst?: boolean } = $props();
	const chips = $derived(headChips(result));
</script>

{#if chips.chips.length || assumed.length || checkFirst}
	<div class="cp-headchips">
		<span class="cp-vchips">
			{#each chips.chips as c (c.input)}
				<span class="cp-vchip cp-vchip--{c.kind}" title={c.title}>
					{#if c.kind === 'prefilled'}<span class="cp-vdot" aria-hidden="true"></span>{/if}
					{#if c.kind === 'exam'}<Icon name="exam" size={11} />{/if}
					{#if c.full}<span aria-hidden="true">{c.text}</span><span class="cp-sr-only">{c.full}</span>{:else}{c.text}{/if}{#if c.kind === 'exam'}<span class="cp-sr-only">{' (set by the exam)'}</span>{/if}
				</span>
			{/each}
			{#if chips.more}<span class="cp-vchip cp-vchip--more">+{chips.more}</span>{/if}
		</span>
		<AssumedChip {assumed} {checkFirst} />
	</div>
{/if}

<style>
	.cp-headchips {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-top: 6px;
	}
	.cp-vchips {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		min-width: 0;
	}
	.cp-vchip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 1px 7px;
		border-radius: 5px;
		font-size: 12px;
		font-weight: 500;
		line-height: 1.5;
		font-variant-numeric: tabular-nums;
		color: var(--rv-text);
		background: var(--rv-surface-hover);
		border: 1px solid transparent;
		white-space: nowrap;
	}
	.cp-vchip--prefilled {
		background: transparent;
		border-color: color-mix(in srgb, var(--rv-amber-line) 60%, transparent);
	}
	.cp-vdot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: var(--rv-amber-line);
	}
	.cp-vchip--assumed {
		background: transparent;
		border: 1px dashed var(--rv-border-strong);
		color: var(--rv-muted);
	}
	.cp-vchip--exam {
		background: transparent;
		border-color: var(--rv-border);
		color: var(--rv-muted);
	}
	.cp-vchip--more {
		background: transparent;
		color: var(--rv-muted);
	}
</style>
