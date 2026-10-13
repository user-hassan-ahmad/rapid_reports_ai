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
		wordingProblem,
		HABIT_WHERE_HINT,
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

	/** The edit fields open with the cursor in the first one. */
	function focusOnOpen(node: HTMLInputElement) {
		node.focus();
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
				class="choice-chip {selectedOf(c) === ch.id ? 'choice-chip-on' : ''}"
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
		<p class="evidence-quote">{evidenceLine(e)}</p>
	{/each}
{/snippet}

{#snippet card(c: DecisionCard)}
	<section class="panel-card space-y-2.5" aria-label={c.title}>
		<h4 class="card-title">{c.title}</h4>
		{#if c.note}<p class="text-xs text-amber-300/80">{c.note}</p>{/if}
		{@render evidence(c)}
		{#if c.usual}
			{#each Object.entries(c.usual) as [state, text] (state)}
				{#if text}<p class="card-body">{stateLabel(state)}: “{text}”</p>{/if}
			{/each}
		{:else if c.wording && c.kind === 'concept'}
			{#if c.wording.default}<p class="card-body">Usually: “{c.wording.default}”</p>{/if}
			{#if c.wording.when_met}
				<p class="card-body">When {c.wording.condition || 'it applies'}: “{c.wording.when_met}”</p>
			{:else if c.wording.default && c.wording.condition}
				<p class="card-note">Left out when {c.wording.condition}.</p>
			{/if}
		{:else if c.kind === 'habit' && c.habit}
			{#if c.habit.question}<p class="card-body">Ask: “{c.habit.question}”</p>{/if}
			{#if c.habit.yes}
				<p class="card-note">Yes: “{c.habit.yes}” · No: “{c.habit.no}”</p>
			{:else}
				<p class="card-note">State: “{c.habit.no}”</p>
			{/if}
		{:else if c.wording?.text}
			<p class="card-body">“{c.wording.text}”</p>
		{/if}
		{@render chips(c)}
		{#if editing === c.id}
			{@const editChoice = c.choices.find((x) => x.choice === null)?.id ?? 'edit'}
			<div class="space-y-2.5 border-t border-white/[0.06] pt-3">
				{#if c.ledger_kind === 'concept'}
					<label class="field-label"
						>Usually
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.default} use:focusOnOpen />
					</label>
					<label class="field-label"
						>When it applies
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.when_met} />
					</label>
					{#if draft.condition}<p class="card-note">It applies when {draft.condition}.</p>{/if}
				{:else if c.ledger_kind === 'habit'}
					<label class="field-label"
						>When this is reported
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.condition} use:focusOnOpen />
					</label>
					<p class="card-note">{HABIT_WHERE_HINT}</p>
					<label class="field-label"
						>Question
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.question} />
					</label>
					<label class="field-label"
						>Yes writes
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.yes} />
					</label>
					<label class="field-label"
						>No writes
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.no} />
					</label>
				{:else}
					<label class="field-label"
						>Wording
						<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.text} use:focusOnOpen />
					</label>
				{/if}
				{#if wordingProblem(c, draft)}<p class="text-xs text-amber-300/80" role="status">{wordingProblem(c, draft)}</p>{/if}
				<button
					type="button"
					class="btn-primary btn-compact"
					onclick={() => useWording(c, editChoice)}
					disabled={busy || !changeFor(c, { choiceId: editChoice, edited: draft }, source)}>Use this wording</button
				>
			</div>
		{/if}
	</section>
{/snippet}

{#snippet entry(c: DecisionCard)}
	{#if c.kind === 'group'}
		<div class="panel-card-quiet space-y-3">
			<button
				type="button"
				class="focus-ring rounded-md text-left text-xs font-medium text-gray-300 transition-colors hover:text-white"
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

<div class="space-y-4">
	{#if notice}<p class="text-xs text-amber-300/80" role="status">{notice}</p>{/if}

	{#if valueCards.length || mode === 'review' || added.length}
		<section class="panel-card space-y-4" aria-label="Required values">
			<div class="flex items-center gap-2"><h4 class="section-label">Required values</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
			{#each valueCards as c (c.id)}
				<div class="space-y-2">
					<p class="card-title">{c.title}</p>
					{#if c.note}<p class="text-xs text-amber-300/80">{c.note}</p>{/if}
					{@render evidence(c)}
					{@render chips(c)}
				</div>
			{/each}
			{#each added as name (name)}
				<p class="card-title">{name} <span class="text-xs font-normal text-gray-500">(every report)</span></p>
			{/each}
			<div class="flex gap-2">
				<input
					class="input-dark input-compact flex-1"
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
				<button type="button" class="btn-secondary btn-compact" onclick={addValue} disabled={!validValueName(newValue)}>+ Add</button>
			</div>
		</section>
	{/if}

	{#each otherCards as c (c.id)}
		{@render card(c)}
	{/each}

	{#if moreCount}
		<button
			type="button"
			class="focus-ring rounded-md text-xs font-medium text-purple-300/80 transition-colors hover:text-purple-200"
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
			class="focus-ring rounded-md text-xs font-medium text-purple-300/80 transition-colors hover:text-purple-200"
			aria-expanded={showKept}
			onclick={() => (showKept = !showKept)}
		>
			Kept as-is ({keptLeft.length})
		</button>
		{#if showKept}
			<ul class="space-y-1">
				{#each keptLeft as c (c.id)}
					<li class="flex items-center justify-between rounded-md px-2 py-1 text-xs text-gray-400 hover:bg-white/[0.03]">
						<span>{c.title}: {c.choices.find((x) => x.id === c.selected)?.label}</span>
						<button
							type="button"
							class="focus-ring rounded text-purple-300/80 hover:text-purple-200"
							aria-label="Change {c.title}"
							onclick={() => (promoted = [...promoted, c.id])}>Change</button
						>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}

	<div class="flex justify-end gap-2 border-t border-white/[0.06] pt-4">
		{#if onSkip}
			<button type="button" class="btn-ghost" onclick={() => onSkip?.(changesOnSkip(defaults))} disabled={busy}>Skip</button>
		{/if}
		<button type="button" class="btn-primary" onclick={finish} disabled={busy}>
			{mode === 'review' ? 'Apply' : 'Continue'}
		</button>
	</div>
</div>
