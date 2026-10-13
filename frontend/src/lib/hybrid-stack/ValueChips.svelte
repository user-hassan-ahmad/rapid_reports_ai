<script lang="ts">
	// The value cluster (requirements spec 2026-10-12 part 1): the template's required values as one wrapped line of
	// chips at the top of the scratchpad. Filled from the dictation (its source on hover), typed, N/A, open, "stated?"
	// (stated, no sentence named: needs a look) or filling. Open and "stated?" chips block Confirm. Click a chip to
	// type its value; "Mark rest N/A" closes every open one (a sequence not acquired). Each chip is a walkthrough stop
	// (data-stop "value:<item>"), ringed while it is the current stop.
	import { tick } from 'svelte';
	import { chipLabel } from './values';
	import type { ValueChip } from './types';

	let {
		values,
		current = null,
		onEnter,
		onNa,
		onRestNa,
		onKeep
	}: {
		values: ValueChip[];
		/** The walkthrough's current stop ("value:<item>" rings that chip). */
		current?: string | null;
		/** A typed value (empty: the chip opens again). */
		onEnter: (item: string, text: string) => void;
		onNa: (item: string) => void;
		onRestNa: () => void;
		/** A "stated?" chip kept as stated. */
		onKeep: (item: string) => void;
	} = $props();

	let editing: string | null = $state(null);
	let text = $state('');
	const openCount = $derived(values.filter((v) => v.state === 'open').length);
	const tone: Record<ValueChip['state'], string> = {
		filled: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200',
		entered: 'border-sky-400/30 bg-sky-500/10 text-sky-200',
		na: 'border-white/10 bg-white/[0.03] text-gray-500',
		open: 'border-amber-400/50 bg-amber-500/10 text-amber-200',
		check: 'border-orange-400/50 bg-orange-500/10 text-orange-200',
		filling: 'border-white/10 bg-white/[0.03] text-gray-400 animate-pulse'
	};
	const ring = (v: ValueChip) => (current === `value:${v.item}` ? 'ring-2 ring-orange-400/60' : '');

	async function edit(v: ValueChip) {
		editing = v.item;
		text = v.value ?? '';
		await tick();
		document.querySelector<HTMLInputElement>('[data-testid="value-input"]')?.focus();
	}
	function save() {
		if (editing === null) return;
		onEnter(editing, text);
		editing = null;
	}
	function na() {
		if (editing === null) return;
		onNa(editing);
		editing = null;
	}
	function keep() {
		if (editing === null) return;
		onKeep(editing);
		editing = null;
	}
	function key(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			editing = null;
		}
	}
	const title = (v: ValueChip) =>
		v.state === 'filled' && v.quote ? `From the dictation: "${v.quote}"`
		: v.state === 'check' ? 'Stated in the dictation, but no single sentence gives its value: check it'
		: v.state === 'filling' ? 'Reading the dictation…'
		: v.state === 'open' ? 'Click to type the value' : 'Click to change';
</script>

{#if values.length}
	<section aria-label="Required values" data-testid="value-cluster"
		class="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2 text-xs">
		<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Required values</span>
		{#each values as v (v.item)}
			{#if editing === v.item}
				<span class="flex items-center gap-1 rounded {ring(v)}" data-stop={`value:${v.item}`}>
					<span class="text-gray-300">{v.item}</span>
					<input data-testid="value-input" aria-label={`Value for ${v.item}`} bind:value={text} onkeydown={key}
						class="w-24 rounded border border-white/15 bg-black/30 px-1.5 py-0.5 text-gray-100" />
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-300 hover:bg-white/[0.06]" onclick={save}>Save</button>
					{#if v.state === 'check'}
						<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-emerald-200 hover:bg-white/[0.06]" onclick={keep}>Stated ✓</button>
					{/if}
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={na}>N/A</button>
				</span>
			{:else}
				<button type="button" class="rounded border px-1.5 py-0.5 {tone[v.state]} {ring(v)}" data-state={v.state} data-stop={`value:${v.item}`}
					title={title(v)} onclick={() => edit(v)}>{chipLabel(v)}</button>
			{/if}
		{/each}
		{#if openCount}
			<button type="button" class="ml-auto rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={onRestNa}>Mark rest N/A</button>
		{/if}
	</section>
{/if}
