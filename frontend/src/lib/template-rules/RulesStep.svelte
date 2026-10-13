<script lang="ts">
	/**
	 * The Rules step (spec 2026-10-13-template-rules-step-design, "Cards"): exceptions only, quoted evidence, about 8
	 * decisions; the rest under "More decisions" (where groups stay collapsed until opened); items every example
	 * agrees on folded into "Kept as-is". No "confirm all". Continue sends the answers (plus the kept defaults); Skip
	 * records the pre-ticked defaults. Cards speak in report behaviour; the sheet is never shown.
	 * Used by the creator (mode "create") and the refine panel's review (mode "review").
	 */
	import {
		changeFor,
		changesOnContinue,
		changesOnSkip,
		editWording,
		evidenceLine,
		flatCards,
		validValueName,
		type Answer
	} from './cards';
	import type { CardWording, DecisionCard, DecisionChange } from './types';

	let {
		cards,
		more = [],
		kept = [],
		defaults = [],
		notice = '',
		mode = 'create',
		busy = false,
		onContinue,
		onSkip
	}: {
		cards: DecisionCard[];
		more?: DecisionCard[];
		kept?: DecisionCard[];
		defaults?: DecisionChange[];
		notice?: string;
		mode?: 'create' | 'review';
		busy?: boolean;
		onContinue: (changes: DecisionChange[]) => void;
		onSkip?: (changes: DecisionChange[]) => void;
	} = $props();

	let answers = $state<Record<string, Answer>>({});
	let editing = $state<string | null>(null);
	let draft = $state<CardWording>({});
	let showMore = $state(false);
	let showKept = $state(false);
	let openGroups = $state<string[]>([]);
	let promoted = $state<string[]>([]);
	let added = $state<string[]>([]);
	let newValue = $state('');

	const source = $derived(mode === 'review' ? 'first_use_review' : 'creation');
	const keptLeft = $derived(kept.filter((c) => !promoted.includes(c.id)));
	const openCards = $derived([...cards, ...kept.filter((c) => promoted.includes(c.id))]);
	const valueCards = $derived(openCards.filter((c) => c.kind === 'value'));
	const otherCards = $derived(openCards.filter((c) => c.kind !== 'value'));
	const moreCount = $derived(flatCards(more).length);

	function selectedOf(c: DecisionCard): string | null {
		return answers[c.id]?.choiceId ?? c.selected;
	}

	function stateLabel(state: string): string {
		const s = state.replace(/_/g, ' ');
		return s.charAt(0).toUpperCase() + s.slice(1);
	}

	function choose(c: DecisionCard, choiceId: string) {
		const ch = c.choices.find((x) => x.id === choiceId);
		if (ch && ch.choice === null) {
			draft = editWording(c, selectedOf(c));
			editing = c.id;
			return;
		}
		answers = { ...answers, [c.id]: { choiceId } };
		if (editing === c.id) editing = null;
	}

	function useWording(c: DecisionCard, choiceId: string) {
		const a: Answer = { choiceId, edited: { ...draft } };
		if (!changeFor(c, a, source)) return;
		answers = { ...answers, [c.id]: a };
		editing = null;
	}

	function toggleGroup(id: string) {
		openGroups = openGroups.includes(id) ? openGroups.filter((x) => x !== id) : [...openGroups, id];
	}

	function addValue() {
		const n = newValue.trim();
		if (!validValueName(n) || added.some((x) => x.toLowerCase() === n.toLowerCase())) return;
		added = [...added, n];
		newValue = '';
	}

	function finish() {
		onContinue(changesOnContinue([...cards, ...more], kept, answers, added, source));
	}
</script>

{#snippet chips(c: DecisionCard)}
	<div class="flex flex-wrap gap-1.5">
		{#each c.choices as ch (ch.id)}
			<button
				type="button"
				class="text-xs px-2.5 py-1 rounded-full border transition-colors {selectedOf(c) === ch.id
					? 'border-purple-400 bg-purple-500/20 text-white'
					: 'border-white/10 text-gray-400 hover:text-gray-200'}"
				aria-pressed={selectedOf(c) === ch.id}
				aria-label="{c.title}: {ch.label}"
				onclick={() => choose(c, ch.id)}
				disabled={busy}>{ch.label}</button
			>
		{/each}
	</div>
{/snippet}

{#snippet evidence(c: DecisionCard)}
	{#each c.evidence as e, i (i)}
		<p class="text-xs text-gray-500">{evidenceLine(e)}</p>
	{/each}
{/snippet}

{#snippet card(c: DecisionCard)}
	<section class="rounded-lg border border-white/10 p-3 space-y-2" aria-label={c.title}>
		<h4 class="text-sm text-gray-200">{c.title}</h4>
		{#if c.note}<p class="text-xs text-amber-300/80">{c.note}</p>{/if}
		{@render evidence(c)}
		{#if c.usual}
			{#each Object.entries(c.usual) as [state, text] (state)}
				{#if text}<p class="text-xs text-gray-300">{stateLabel(state)}: “{text}”</p>{/if}
			{/each}
		{:else if c.wording && c.kind === 'concept'}
			{#if c.wording.default}<p class="text-xs text-gray-300">Usually: “{c.wording.default}”</p>{/if}
			{#if c.wording.when_met}
				<p class="text-xs text-gray-300">When {c.wording.condition || 'it applies'}: “{c.wording.when_met}”</p>
			{:else if c.wording.default && c.wording.condition}
				<p class="text-xs text-gray-400">Left out when {c.wording.condition}.</p>
			{/if}
		{:else if c.wording?.text}
			<p class="text-xs text-gray-300">“{c.wording.text}”</p>
		{/if}
		{@render chips(c)}
		{#if editing === c.id}
			{@const editChoice = c.choices.find((x) => x.choice === null)?.id ?? 'edit'}
			<div class="space-y-1.5">
				{#if c.ledger_kind === 'concept'}
					<label class="block text-xs text-gray-400"
						>Usually
						<input class="input w-full text-sm" bind:value={draft.default} />
					</label>
					<label class="block text-xs text-gray-400"
						>When it applies
						<input class="input w-full text-sm" bind:value={draft.when_met} />
					</label>
					{#if draft.condition}<p class="text-xs text-gray-500">It applies when {draft.condition}.</p>{/if}
				{:else}
					<label class="block text-xs text-gray-400"
						>Wording
						<input class="input w-full text-sm" bind:value={draft.text} />
					</label>
				{/if}
				<button type="button" class="btn-primary text-xs" onclick={() => useWording(c, editChoice)}>Use this wording</button>
			</div>
		{/if}
	</section>
{/snippet}

{#snippet entry(c: DecisionCard)}
	{#if c.kind === 'group'}
		<div class="rounded-lg border border-white/5 p-2 space-y-2">
			<button
				type="button"
				class="text-xs text-gray-400 hover:text-gray-200 text-left"
				aria-expanded={openGroups.includes(c.id)}
				onclick={() => toggleGroup(c.id)}>{c.title}</button
			>
			{#if openGroups.includes(c.id)}
				{#each c.cards ?? [] as inner (inner.id)}
					{@render card(inner)}
				{/each}
			{/if}
		</div>
	{:else}
		{@render card(c)}
	{/if}
{/snippet}

<div class="space-y-3">
	{#if notice}<p class="text-xs text-amber-300/80">{notice}</p>{/if}

	{#if valueCards.length || mode === 'review' || added.length}
		<section class="rounded-lg border border-white/10 p-3 space-y-3" aria-label="Required values">
			<h4 class="text-sm text-gray-200">Required values</h4>
			{#each valueCards as c (c.id)}
				<div class="space-y-1">
					<p class="text-sm text-gray-300">{c.title}</p>
					{#if c.note}<p class="text-xs text-amber-300/80">{c.note}</p>{/if}
					{@render evidence(c)}
					{@render chips(c)}
				</div>
			{/each}
			{#each added as name (name)}
				<p class="text-sm text-gray-300">{name} <span class="text-xs text-gray-500">(every report)</span></p>
			{/each}
			<div class="flex gap-2">
				<input
					class="input flex-1 text-sm"
					placeholder="Add a value"
					aria-label="Add a value"
					bind:value={newValue}
					onkeydown={(e) => {
						if (e.key === 'Enter') {
							e.preventDefault();
							addValue();
						}
					}}
				/>
				<button type="button" class="btn-ghost text-xs" onclick={addValue} disabled={!validValueName(newValue)}>+ Add</button>
			</div>
		</section>
	{/if}

	{#each otherCards as c (c.id)}
		{@render card(c)}
	{/each}

	{#if moreCount}
		<button
			type="button"
			class="text-xs text-gray-400 hover:text-gray-200"
			aria-expanded={showMore}
			onclick={() => (showMore = !showMore)}
		>
			More decisions ({moreCount})
		</button>
		{#if showMore}
			{#each more as c (c.id)}
				{@render entry(c)}
			{/each}
		{/if}
	{/if}

	{#if keptLeft.length}
		<button
			type="button"
			class="text-xs text-gray-400 hover:text-gray-200"
			aria-expanded={showKept}
			onclick={() => (showKept = !showKept)}
		>
			Kept as-is ({keptLeft.length})
		</button>
		{#if showKept}
			<ul class="space-y-1">
				{#each keptLeft as c (c.id)}
					<li class="flex items-center justify-between text-xs text-gray-400">
						<span>{c.title}: {c.choices.find((x) => x.id === c.selected)?.label}</span>
						<button
							type="button"
							class="text-gray-500 hover:text-gray-200"
							aria-label="Change {c.title}"
							onclick={() => (promoted = [...promoted, c.id])}>Change</button
						>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	<div class="flex justify-end gap-2 pt-2">
		{#if onSkip}
			<button type="button" class="btn-ghost text-sm" onclick={() => onSkip?.(changesOnSkip(defaults))} disabled={busy}>Skip</button>
		{/if}
		<button type="button" class="btn-primary text-sm" onclick={finish} disabled={busy}>
			{mode === 'review' ? 'Apply' : 'Continue'}
		</button>
	</div>
</div>
