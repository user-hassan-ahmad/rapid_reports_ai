<script lang="ts">
	/** The head's assumptions cue. Exactly one assumption is named in full ("⚠ assumes: <label> <value>", cut with an ellipsis only when the head overflows); several read
	 *  "⚠ N assumed". The full list is in the tooltip AND in visually hidden text, so the card head's accessible name
	 *  carries it; the assumed values themselves lead the card's value list. A check_first preview with nothing
	 *  assumed (an odd backend state) still gets a visible "⚠ check first". */
	let { assumed, checkFirst = false }: { assumed: string[]; checkFirst?: boolean } = $props();
	const n = $derived(assumed.length);
	// "Label: value" → "<label> <value>", in full: the chip itself truncates (ellipsis) only when the head overflows
	const one = $derived.by(() => {
		if (n !== 1) return '';
		const [label, ...rest] = assumed[0].split(': ');
		return rest.length ? `${label} ${rest.join(': ')}` : label;
	});
</script>

{#if n}
	<span class="cp-chip cp-chip-warn cp-assumed-chip" title={`Assumed:\n${assumed.join('\n')}`}
		>{#if n === 1}<span class="cp-assumed-one">⚠ assumes: {one}</span>{:else}⚠ {n} assumed{/if}<span class="cp-sr-only"
			>{` assumed: ${assumed.join('; ')}`}</span
		></span
	>
{:else if checkFirst}
	<span class="cp-chip cp-chip-warn" title="An eligibility question could change this outcome">⚠ check first</span>
{/if}

<style>
	.cp-assumed-chip {
		display: inline-flex;
		max-width: 100%;
		min-width: 0;
	}
	.cp-assumed-one {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
