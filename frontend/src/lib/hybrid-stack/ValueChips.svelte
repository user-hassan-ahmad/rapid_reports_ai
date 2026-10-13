<script lang="ts">
	// The value cluster (requirements spec 2026-10-12 part 1): the template's required values as one wrapped line of
	// chips at the top of the scratchpad. Filled from the dictation (its source on hover), typed, N/A, open, "stated?"
	// (stated, no sentence named: needs a look) or filling. Open and "stated?" chips block Confirm. Click a chip to
	// type its value; "Mark rest N/A" closes every open one (a sequence not acquired). Each chip is a walkthrough stop
	// (data-stop "value:<item>"), ringed while it is the current stop and opened to type. An editor holding unsaved
	// text is reported up (onDraft) so Confirm waits for it. An open chip's editor lists the dictation's number clauses
	// (picks): one tap enters a clause's one number, or shows its numbers to choose from. A conflict chip ("check" with a
	// value: two or more numbers mapped to the item) shows each number with its sentence (onPick enters the number and
	// records the clause).
	import { tick, untrack } from 'svelte';
	import { chipLabel } from './values';
	import type { ClausePick, ValueChip } from './types';

	let {
		values,
		current = null,
		onEnter,
		onNa,
		onRestNa,
		onKeep,
		onPick = () => {},
		onDraft = () => {}
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
		/** A number tapped from a dictation clause: picked (never stated as a typed answer), with the clause recorded. */
		onPick?: (item: string, value: string, clause: string) => void;
		/** An editor is open with text that differs from its chip (true) or not (false). */
		onDraft?: (dirty: boolean) => void;
	} = $props();

	let editing: string | null = $state(null);
	let text = $state('');
	// An open chip's pick holding several numbers: its numbers are shown to choose from
	let pickFrom: ClausePick | null = $state(null);
	let input: HTMLInputElement | null = $state(null);
	const chipEls: Record<string, HTMLButtonElement | null> = $state({});
	const dirty = $derived(editing !== null && text.trim() !== (values.find((v) => v.item === editing)?.value ?? ''));
	$effect(() => onDraft(dirty));
	// The walkthrough reaching a chip opens it to type (only when the stop changes: Escape leaves it closed)
	$effect(() => {
		const stop = current;
		untrack(() => {
			const v = stop?.startsWith('value:') ? values.find((x) => `value:${x.item}` === stop) : null;
			if (v && editing !== v.item) void edit(v);
		});
	});
	const openCount = $derived(values.filter((v) => v.state === 'open').length);
	const tone: Record<ValueChip['state'], string> = {
		filled: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200',
		picked: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200',
		entered: 'border-sky-400/30 bg-sky-500/10 text-sky-200',
		na: 'border-white/10 bg-white/[0.03] text-gray-500',
		open: 'border-amber-400/50 bg-amber-500/10 text-amber-200',
		check: 'border-orange-400/50 bg-orange-500/10 text-orange-200',
		filling: 'border-white/10 bg-white/[0.03] text-gray-400 animate-pulse'
	};
	const ring = (v: ValueChip) => (current === `value:${v.item}` ? 'ring-2 ring-orange-400/60' : '');

	async function edit(v: ValueChip) {
		editing = v.item;
		pickFrom = null;
		text = v.value ?? '';
		await tick();
		input?.focus();
	}
	/** Close the editor and give focus back to its chip. */
	async function close() {
		const item = editing;
		editing = null;
		await tick();
		if (item !== null) chipEls[item]?.focus();
	}
	function save() {
		if (editing === null) return;
		onEnter(editing, text);
		void close();
	}
	function na() {
		if (editing === null) return;
		onNa(editing);
		void close();
	}
	function choose(value: string, clause: string) {
		if (editing === null) return;
		onPick(editing, value, clause);
		void close();
	}
	function pickClause(p: ClausePick) {
		if (p.value) choose(p.value, p.clause);
		else pickFrom = p;
	}
	function keep() {
		if (editing === null) return;
		onKeep(editing);
		void close();
	}
	function key(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			void close();
		}
	}
	const title = (v: ValueChip) =>
		v.state === 'filled' && v.quote ? `From the dictation: "${v.quote}"`
		: v.state === 'picked' ? `Picked from the dictation: "${v.picked_clause ?? v.quote}"`
		: v.state === 'check' && v.value ? 'Two or more numbers in the dictation give this value: pick one'
		: v.state === 'check' ? 'Stated in the dictation, but no number gives its value: check it'
		: v.state === 'filling' ? 'Reading the dictation…'
		: v.state === 'open' ? 'Click to type the value' : 'Click to change';
	const said: Record<ValueChip['state'], string> = {
		filled: 'from dictation',
		picked: 'picked from dictation',
		entered: 'typed',
		na: 'not applicable',
		open: 'needs a value',
		check: 'stated in dictation, needs a look',
		filling: 'reading the dictation'
	};
	const ariaLabel = (v: ValueChip) =>
		`${chipLabel(v)}, ${v.state === 'filled' && v.kept ? 'stated in dictation, kept' : v.state === 'check' && v.value ? 'more than one number, pick one' : said[v.state]}`;
</script>

{#if values.length}
	<section aria-label="Required values" data-testid="value-cluster"
		class="flex flex-wrap items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2 text-xs">
		<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Required values</span>
		{#each values as v (v.item)}
			{#if editing === v.item}
				<span class="flex items-center gap-1 rounded {ring(v)}" data-testid="value-editor" data-stop={`value:${v.item}`}>
					<span class="text-gray-300">{v.item}</span>
					<input bind:this={input} data-testid="value-input" aria-label={`Value for ${v.item}`} bind:value={text} onkeydown={key}
						class="w-24 rounded border border-white/15 bg-black/30 px-1.5 py-0.5 text-gray-100" />
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-300 hover:bg-white/[0.06]" onclick={save}>Save</button>
					{#if v.state === 'check' && !v.value}
						<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-emerald-200 hover:bg-white/[0.06]" onclick={keep}>Stated ✓</button>
					{/if}
					<button type="button" class="rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={na}>N/A</button>
				</span>
				{@const choices = pickFrom ? [pickFrom] : v.state === 'check' && v.picks?.length ? v.picks : null}
				{#if choices}
					<span class="flex basis-full flex-col gap-1 pl-1" data-testid="value-numbers">
						{#each choices as ch, j (j)}
							<span class="flex flex-wrap items-center gap-1">
								{#each ch.value ? [ch.value] : ch.numbers as n, i (i)}
									<button type="button" class="rounded border border-sky-400/30 px-1.5 py-0.5 text-sky-200 hover:bg-sky-500/10" onclick={() => choose(n, ch.clause)}>{n}</button>
								{/each}
								<span class="text-gray-400">"{ch.clause}"</span>
							</span>
						{/each}
					</span>
				{:else if v.state === 'open' && v.picks?.length}
					<span class="flex basis-full flex-wrap items-center gap-1 pl-1" data-testid="value-picks">
						<span class="text-gray-500">From the dictation:</span>
						{#each v.picks as p, i (i)}
							<button type="button" class="max-w-full truncate rounded border border-white/15 px-1.5 py-0.5 text-gray-300 hover:bg-white/[0.06]" title={p.clause} onclick={() => pickClause(p)}>{p.clause}</button>
						{/each}
					</span>
				{/if}
			{:else}
				<button type="button" class="rounded border px-1.5 py-0.5 {tone[v.state]} {ring(v)}" data-state={v.state} data-stop={`value:${v.item}`}
					bind:this={chipEls[v.item]} aria-label={ariaLabel(v)} title={title(v)} onclick={() => edit(v)}>{chipLabel(v)}</button>
			{/if}
		{/each}
		{#if openCount}
			<button type="button" class="ml-auto rounded border border-white/15 px-1.5 py-0.5 text-gray-400 hover:bg-white/[0.06]" onclick={onRestNa}>Mark rest N/A</button>
		{/if}
	</section>
{/if}
