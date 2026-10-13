<script lang="ts">
	/**
	 * The Style step's checks (spec 2026-10-13-template-rules-step-design, cards "Always printed" and "Your normal
	 * report"; plan Phase 5), shown as report behaviour, never as the sheet. Every tap is one ledger change, applied at
	 * once by the parent (postApplyDecisions), which then reloads these checks so the answered card goes away. A part
	 * that failed on the server is simply empty: the Style step shows the summary without it.
	 */
	import { changeFor, editWording } from './cards';
	import type { CardWording, ChangeSource, DecisionCard, DecisionChange, NormalSentence, SheetChecksResponse } from './types';

	let {
		checks,
		source = 'creation',
		busy = false,
		error = '',
		onChange
	}: {
		checks: SheetChecksResponse | null;
		source?: ChangeSource;
		busy?: boolean;
		/** the parent's message when an apply failed (shown here, next to the open editor) */
		error?: string;
		/** applies the change; resolving to false means it failed, and the open editor keeps its draft */
		onChange: (changes: DecisionChange[]) => void | boolean | Promise<void | boolean>;
	} = $props();

	let editing = $state<string | null>(null);
	let draft = $state<CardWording>({});
	let failed = $state(false);

	/** The edit field opens with the cursor in it. */
	function focusOnOpen(node: HTMLInputElement) {
		node.focus();
	}

	function open(id: string, wording: CardWording) {
		editing = id;
		draft = wording;
		failed = false;
	}

	function close() {
		editing = null;
		failed = false;
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	/** Apply; the editor closes only when the apply succeeded. */
	async function apply(change: DecisionChange | null) {
		if (!change) return;
		const ok = await onChange([change]);
		if (ok === false) failed = true;
		else close();
	}

	function tap(card: DecisionCard, choiceId: string) {
		const ch = card.choices.find((x) => x.id === choiceId);
		if (ch && ch.choice === null) {
			// a concept is edited as its two wordings (the condition stays the card's); anything else as one sentence
			open(card.id, card.ledger_kind === 'concept' ? editWording(card, null) : { text: card.wording?.text ?? '' });
			return;
		}
		const change = changeFor(card, { choiceId }, source);
		if (change) void onChange([change]);
	}

	function cardChange(card: DecisionCard): DecisionChange | null {
		const editId = card.choices.find((x) => x.choice === null)?.id ?? 'edit';
		return changeFor(card, { choiceId: editId, edited: { ...draft } }, source);
	}

	function sentenceChange(s: NormalSentence, text: string): DecisionChange {
		return { kind: 'normal', key: s.key, choice: { text: text.trim() }, source };
	}
</script>

{#snippet chips(card: DecisionCard)}
	<div class="flex flex-wrap gap-1.5">
		{#each card.choices as ch (ch.id)}
			<button
				type="button"
				class="text-xs px-2.5 py-1 rounded-full border border-white/10 text-gray-400 hover:text-gray-200"
				aria-label="{card.title}: {ch.label}"
				onclick={() => tap(card, ch.id)}
				disabled={busy}>{ch.label}</button
			>
		{/each}
	</div>
	{#if editing === card.id}
		<div class="space-y-1.5 pt-1.5" role="group" onkeydown={onKey}>
			{#if card.ledger_kind === 'concept'}
				<label class="block text-xs text-gray-400"
					>Usually
					<input class="input w-full text-sm" bind:value={draft.default} use:focusOnOpen />
				</label>
				<label class="block text-xs text-gray-400"
					>When it applies
					<input class="input w-full text-sm" bind:value={draft.when_met} />
				</label>
				{#if draft.condition}<p class="text-xs text-gray-500">It applies when {draft.condition}.</p>{/if}
			{:else}
				<input class="input w-full text-sm" aria-label="Wording for {card.title}" bind:value={draft.text} use:focusOnOpen />
			{/if}
			{@render editorButtons(() => apply(cardChange(card)), !cardChange(card))}
		</div>
	{/if}
{/snippet}

{#snippet editorButtons(save: () => void, invalid: boolean)}
	<div class="flex gap-2">
		<button type="button" class="btn-primary text-xs" onclick={save} disabled={busy || invalid}>Save</button>
		<button type="button" class="btn-ghost text-xs" onclick={close} disabled={busy}>Cancel</button>
	</div>
	{#if failed && error}<p class="text-xs text-red-400" role="alert">{error}</p>{/if}
{/snippet}

{#snippet cardBox(card: DecisionCard, quoted: boolean)}
	<div class="rounded-lg border border-white/10 p-3 space-y-1.5">
		<p class="text-sm text-gray-300">{quoted ? `“${card.title}”` : card.title}</p>
		{#if card.note}<p class="text-xs text-gray-500">{card.note}</p>{/if}
		{@render chips(card)}
	</div>
{/snippet}

{#if checks}
	<div class="space-y-4">
		{#if checks.unmatched_cards.length}
			<section class="space-y-2" aria-label="Needs a look">
				<h4 class="text-sm text-gray-200">Needs a look</h4>
				{#each checks.unmatched_cards as card (card.id)}
					{@render cardBox(card, card.ledger_kind === 'fixed')}
				{/each}
			</section>
		{/if}

		{#if checks.duplicate_cards.length}
			<section class="space-y-2" aria-label="May be stated twice">
				<h4 class="text-sm text-gray-200">May be stated twice</h4>
				{#each checks.duplicate_cards as card (card.id)}
					{@render cardBox(card, true)}
				{/each}
			</section>
		{/if}

		{#if checks.fixed_cards.length}
			<section class="space-y-2" aria-label="Always printed">
				<h4 class="text-sm text-gray-200">Always printed</h4>
				<p class="text-xs text-gray-500">These sentences go into every report. Each might not be true for every patient.</p>
				{#each checks.fixed_cards as card (card.id)}
					{@render cardBox(card, true)}
				{/each}
			</section>
		{/if}

		{#if checks.normal_report.length}
			<section class="space-y-2" aria-label="Your normal report">
				<h4 class="text-sm text-gray-200">Your normal report</h4>
				<p class="text-xs text-gray-500">What an all-normal report will say. Tap a sentence to edit or remove it.</p>
				{#each checks.normal_report as sec (sec.section)}
					<div class="space-y-1">
						<p class="text-xs uppercase tracking-wider text-gray-500">{sec.header}</p>
						{#each sec.sentences as s (s.key)}
							{#if editing === s.key}
								<div class="space-y-1.5" role="group" onkeydown={onKey}>
									<input class="input w-full text-sm" aria-label="Edit sentence" bind:value={draft.text} use:focusOnOpen />
									<div class="flex gap-2">
										<button type="button" class="btn-primary text-xs" onclick={() => apply(sentenceChange(s, draft.text ?? ''))}
											disabled={!(draft.text ?? '').trim() || busy}>Save</button>
										<button type="button" class="btn-ghost text-xs" onclick={() => apply(sentenceChange(s, ''))} disabled={busy}>Remove</button>
										<button type="button" class="btn-ghost text-xs" onclick={close} disabled={busy}>Cancel</button>
									</div>
									{#if failed && error}<p class="text-xs text-red-400" role="alert">{error}</p>{/if}
								</div>
							{:else}
								<button
									type="button"
									class="block text-left text-sm text-gray-300 hover:text-white"
									aria-label="Edit: {s.text}"
									onclick={() => open(s.key, { text: s.text })}
									disabled={busy}>{s.text}</button
								>
							{/if}
						{/each}
					</div>
				{/each}
			</section>
		{/if}

		{#if checks.uncovered_cards.length}
			<section class="space-y-2" aria-label="Mentioned but no normal sentence">
				<h4 class="text-sm text-gray-200">Mentioned in your examples but no normal sentence</h4>
				{#each checks.uncovered_cards as card (card.id)}
					{@render cardBox(card, false)}
				{/each}
			</section>
		{/if}
	</div>
{/if}
