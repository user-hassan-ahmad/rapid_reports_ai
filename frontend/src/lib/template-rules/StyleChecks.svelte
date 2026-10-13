<script lang="ts">
	/**
	 * The Style step's checks (spec 2026-10-13-template-rules-step-design, cards "Always printed" and "Your normal
	 * report"; plan Phase 5), shown as report behaviour, never as the sheet. Every tap is one ledger change, applied at
	 * once by the parent (postApplyDecisions), which then reloads these checks so the answered card goes away. A part
	 * that failed on the server is simply empty: the Style step shows the summary without it.
	 */
	import { changeFor } from './cards';
	import type { ChangeSource, DecisionCard, DecisionChange, NormalSentence, SheetChecksResponse } from './types';

	let {
		checks,
		source = 'creation',
		busy = false,
		onChange
	}: {
		checks: SheetChecksResponse | null;
		source?: ChangeSource;
		busy?: boolean;
		onChange: (changes: DecisionChange[]) => void;
	} = $props();

	let editing = $state<string | null>(null);
	let draft = $state('');

	/** The edit field opens with the cursor in it. */
	function focusOnOpen(node: HTMLInputElement) {
		node.focus();
	}

	function tap(card: DecisionCard, choiceId: string) {
		const ch = card.choices.find((x) => x.id === choiceId);
		if (ch && ch.choice === null) {
			editing = card.id;
			draft = card.wording?.text ?? '';
			return;
		}
		const change = changeFor(card, { choiceId }, source);
		if (change) onChange([change]);
	}

	function saveCard(card: DecisionCard) {
		const editId = card.choices.find((x) => x.choice === null)?.id ?? 'edit';
		const change = changeFor(card, { choiceId: editId, edited: { text: draft } }, source);
		if (change) onChange([change]);
		editing = null;
	}

	function editSentence(s: NormalSentence) {
		editing = s.key;
		draft = s.text;
	}

	function saveSentence(s: NormalSentence, text: string) {
		onChange([{ kind: 'normal', key: s.key, choice: { text: text.trim() }, source }]);
		editing = null;
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
		<div class="flex gap-2 pt-1.5">
			<input class="input flex-1 text-sm" aria-label="Wording for {card.title}" bind:value={draft} use:focusOnOpen />
			<button type="button" class="btn-primary text-xs" onclick={() => saveCard(card)} disabled={busy || !draft.trim()}>Save</button>
		</div>
	{/if}
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
								<div class="flex gap-2">
									<input class="input flex-1 text-sm" aria-label="Edit sentence" bind:value={draft} use:focusOnOpen />
									<button type="button" class="btn-primary text-xs" onclick={() => saveSentence(s, draft)} disabled={!draft.trim() || busy}>Save</button>
									<button type="button" class="btn-ghost text-xs" onclick={() => saveSentence(s, '')} disabled={busy}>Remove</button>
								</div>
							{:else}
								<button
									type="button"
									class="block text-left text-sm text-gray-300 hover:text-white"
									aria-label="Edit: {s.text}"
									onclick={() => editSentence(s)}
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
