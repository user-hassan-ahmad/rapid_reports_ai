<script lang="ts">
	/** The head's eligibility cue (B0): "⚠ N assumed" with the checks in the tooltip AND in visually hidden
	 *  text, so the card head's accessible name carries them (the list is also a button-driven expander in the body).
	 *  A check_first preview with nothing assumed (an odd backend state) still gets a visible "⚠ check first". */
	let { assumed, checkFirst = false }: { assumed: string[]; checkFirst?: boolean } = $props();
	const n = $derived(assumed.length);
</script>

{#if n}
	<span class="cp-chip cp-chip-warn" title={`Assumed eligible:\n${assumed.join('\n')}`}
		>⚠ {n} assumed<span class="cp-sr-only">{` eligibility ${n === 1 ? 'check' : 'checks'}: ${assumed.join('; ')}`}</span></span
	>
{:else if checkFirst}
	<span class="cp-chip cp-chip-warn" title="An eligibility question could change this outcome">⚠ check first</span>
{/if}
