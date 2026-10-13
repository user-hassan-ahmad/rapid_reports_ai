<script lang="ts">
	/**
	 * The Style step's checks (spec 2026-10-13-template-rules-step-design, cards "Always printed" and "Your normal
	 * report"; plan Phase 5), shown as report behaviour, never as the sheet. Every tap is one ledger change, applied at
	 * once by the parent (postApplyDecisions), which then reloads these checks so the answered card goes away. A part
	 * that failed on the server is simply empty: the Style step shows the summary without it.
	 */
	import { changeFor, editWording, wordingProblem } from './cards';
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

	/** A normal sentence's wording problem (no quotes, nothing to fill in), or null. */
	function sentenceProblem(text: string | undefined): string | null {
		return wordingProblem({ ledger_kind: 'normal' } as DecisionCard, { text: text ?? '' });
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
				class="choice-chip"
				aria-label="{card.title}: {ch.label}"
				onclick={() => tap(card, ch.id)}
				disabled={busy}>{ch.label}</button
			>
		{/each}
	</div>
	{#if editing === card.id}
		<div class="space-y-2.5 border-t border-white/[0.06] pt-3" role="group">
			{#if card.ledger_kind === 'concept'}
				<label class="field-label space-y-1"
					>Usually
					<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.default} use:focusOnOpen onkeydown={onKey} />
				</label>
				<label class="field-label space-y-1"
					>When it applies
					<input class="input-dark input-compact mt-1 w-full normal-case tracking-normal" bind:value={draft.when_met} onkeydown={onKey} />
				</label>
				{#if draft.condition}<p class="card-note">It applies when {draft.condition}.</p>{/if}
			{:else}
				<input class="input-dark input-compact w-full" aria-label="Wording for {card.title}" bind:value={draft.text} use:focusOnOpen onkeydown={onKey} />
			{/if}
			{#if wordingProblem(card, draft)}<p class="text-xs text-amber-300/80" role="status">{wordingProblem(card, draft)}</p>{/if}
			{@render editorButtons(() => apply(cardChange(card)), !cardChange(card))}
		</div>
	{/if}
{/snippet}

{#snippet editorButtons(save: () => void, invalid: boolean)}
	<div class="flex gap-2">
		<button type="button" class="btn-primary btn-compact" onclick={save} disabled={busy || invalid}>Save</button>
		<button type="button" class="btn-ghost btn-compact" onclick={close} disabled={busy}>Cancel</button>
	</div>
	{#if failed && error}<p class="text-xs text-red-400" role="alert">{error}</p>{/if}
{/snippet}

{#snippet cardBox(card: DecisionCard, quoted: boolean)}
	<div class="panel-card space-y-2.5">
		<p class={quoted ? 'text-sm leading-relaxed text-gray-200' : 'card-title'}>{quoted ? `“${card.title}”` : card.title}</p>
		{#if card.note}<p class="evidence-quote">{card.note}</p>{/if}
		{@render chips(card)}
	</div>
{/snippet}

{#if checks}
	<div class="space-y-6">
		{#if checks.unmatched_cards.length}
			<section class="space-y-3" aria-label="Needs a look">
				<div class="flex items-center gap-2"><h4 class="section-label">Needs a look</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
				{#each checks.unmatched_cards as card (card.id)}
					{@render cardBox(card, card.ledger_kind === 'fixed')}
				{/each}
			</section>
		{/if}

		{#if checks.duplicate_cards.length}
			<section class="space-y-3" aria-label="May be stated twice">
				<div class="flex items-center gap-2"><h4 class="section-label">May be stated twice</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
				{#each checks.duplicate_cards as card (card.id)}
					{@render cardBox(card, true)}
				{/each}
			</section>
		{/if}

		{#if checks.fixed_cards.length}
			<section class="space-y-3" aria-label="Always printed">
				<div class="flex items-center gap-2"><h4 class="section-label">Always printed</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
				<p class="card-note">These sentences go into every report. Each might not be true for every patient.</p>
				{#each checks.fixed_cards as card (card.id)}
					{@render cardBox(card, true)}
				{/each}
			</section>
		{/if}

		{#if checks.normal_report.length}
			<section class="space-y-3" aria-label="Your normal report">
				<div class="flex items-center gap-2"><h4 class="section-label">Your normal report</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
				<p class="card-note">What an all-normal report will say. Tap a sentence to edit or remove it.</p>
				<div class="panel-card space-y-4">
				{#each checks.normal_report as sec (sec.section)}
					<div class="space-y-1">
						<p class="field-label pb-0.5 text-purple-300/70">{sec.header}</p>
						{#each sec.sentences as s (s.key)}
							{#if editing === s.key}
								<div class="space-y-2" role="group">
									<input class="input-dark input-compact w-full" aria-label="Edit sentence" bind:value={draft.text} use:focusOnOpen onkeydown={onKey} />
									<div class="flex gap-2">
										<button type="button" class="btn-primary btn-compact" onclick={() => apply(sentenceChange(s, draft.text ?? ''))}
											disabled={!(draft.text ?? '').trim() || !!sentenceProblem(draft.text) || busy}>Save</button>
										<button type="button" class="btn-ghost btn-compact" onclick={() => apply(sentenceChange(s, ''))} disabled={busy}>Remove</button>
										<button type="button" class="btn-ghost btn-compact" onclick={close} disabled={busy}>Cancel</button>
									</div>
									{#if sentenceProblem(draft.text)}<p class="text-xs text-amber-300/80" role="status">{sentenceProblem(draft.text)}</p>{/if}
									{#if failed && error}<p class="text-xs text-red-400" role="alert">{error}</p>{/if}
								</div>
							{:else}
								<button
									type="button"
									class="focus-ring -mx-2 block w-[calc(100%+1rem)] rounded-md px-2 py-1 text-left text-sm leading-relaxed text-gray-300 transition-colors hover:bg-white/[0.04] hover:text-white"
									aria-label="Edit: {s.text}"
									onclick={() => open(s.key, { text: s.text })}
									disabled={busy}>{s.text}</button
								>
							{/if}
						{/each}
					</div>
				{/each}
				</div>
			</section>
		{/if}

		{#if checks.uncovered_cards.length}
			<section class="space-y-3" aria-label="Mentioned but no normal sentence">
				<div class="flex items-center gap-2"><h4 class="section-label">Mentioned in your examples but no normal sentence</h4><div class="h-px flex-1 bg-white/[0.06]"></div></div>
				{#each checks.uncovered_cards as card (card.id)}
					{@render cardBox(card, false)}
				{/each}
			</section>
		{/if}
	</div>
{/if}
