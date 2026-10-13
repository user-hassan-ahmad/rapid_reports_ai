<script lang="ts">
	/** The head's assumptions cue. Exactly one assumption is named ("⚠ assumes: <short label> <value>"); several read
	 *  "⚠ N assumed". The full list is in the tooltip AND in visually hidden text, so the card head's accessible name
	 *  carries it; the assumed values themselves lead the card's value list. A check_first preview with nothing
	 *  assumed (an odd backend state) still gets a visible "⚠ check first". */
	let { assumed, checkFirst = false }: { assumed: string[]; checkFirst?: boolean } = $props();
	const n = $derived(assumed.length);
	const short = (l: string) => {
		const w = l.trim().split(/\s+/);
		return w.length > 3 ? `${w.slice(0, 3).join(' ')}…` : l.trim();
	};
	// "Label: value" → "<short label> <value>"
	const one = $derived.by(() => {
		if (n !== 1) return '';
		const [label, ...rest] = assumed[0].split(': ');
		return rest.length ? `${short(label)} ${rest.join(': ')}` : short(label);
	});
</script>

{#if n}
	<span class="cp-chip cp-chip-warn" title={`Assumed eligible:\n${assumed.join('\n')}`}
		>{#if n === 1}⚠ assumes: {one}{:else}⚠ {n} assumed{/if}<span class="cp-sr-only"
			>{` eligibility ${n === 1 ? 'check' : 'checks'}: ${assumed.join('; ')}`}</span
		></span
	>
{:else if checkFirst}
	<span class="cp-chip cp-chip-warn" title="An eligibility question could change this outcome">⚠ check first</span>
{/if}
