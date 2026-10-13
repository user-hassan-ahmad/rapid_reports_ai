<script lang="ts">
	// One-tap cards inside the refine chat (chat-edit router spec, "Uncertain or rejected changes become cards"): the
	// Rules step's decision cards (prefilled, nothing pre-selected) and the router's proposal cards. Nothing is applied
	// until a tap; the parent posts the answer to /skill-sheet/refine/card.
	import { changeFor, editWording, wordingProblem, type Answer } from '$lib/template-rules/cards';
	import type { CardWording, DecisionCard } from '$lib/template-rules/types';
	import { isHabit, isProposal, type CardAnswer, type ProposalCard, type RouterCard } from './types';

	let {
		cards,
		busy = false,
		onAnswer
	}: { cards: RouterCard[]; busy?: boolean; onAnswer: (answer: CardAnswer) => void } = $props();

	let done = $state<Record<string, string>>({});
	let writing = $state<Record<string, { choiceId: string; wording: CardWording }>>({});
	let problem = $state<Record<string, string>>({});

	const asDecision = (c: RouterCard) => c as DecisionCard;
	const asProposal = (c: RouterCard) => c as ProposalCard;

	function send(card: DecisionCard, a: Answer) {
		if (a.edited) {
			const why = wordingProblem(card, a.edited); // the server's own rules, said before it refuses
			if (why) {
				problem[card.id] = why;
				return;
			}
		}
		const ch = changeFor(card, a, 'chat');
		if (!ch) return;
		done[card.id] = card.choices.find((x) => x.id === a.choiceId)?.label ?? 'Done';
		onAnswer({ kind: ch.kind, key: ch.key, choice: ch.choice });
	}

	function pick(card: DecisionCard, choiceId: string) {
		const c = card.choices.find((x) => x.id === choiceId);
		if (!c) return;
		if (c.choice) send(card, { choiceId });
		else writing[card.id] = { choiceId, wording: editWording(card, choiceId) };
	}

	function apply(card: ProposalCard) {
		done[card.id] = 'Applied';
		onAnswer({ proposal: card.apply });
	}
</script>

<div class="space-y-2.5">
	{#each cards as card (card.id)}
		<div class="panel-card space-y-2.5 p-3.5">
			<p class="card-title">{card.title}</p>
			{#if isHabit(card)}
				<p class="card-note">Nothing in the template changed for it.</p>
			{:else if done[card.id]}
				<p class="card-note">{done[card.id]}</p>
			{:else if isProposal(card)}
				<div class="flex gap-2">
					<button type="button" disabled={busy} onclick={() => apply(asProposal(card))}
						class="btn-primary btn-compact">
						Apply
					</button>
					<button type="button" disabled={busy} onclick={() => (done[card.id] = 'Left as is')}
						class="btn-ghost btn-compact">
						Leave as is
					</button>
				</div>
			{:else if writing[card.id]}
				{@const d = asDecision(card)}
				<div class="space-y-2 border-t border-white/[0.06] pt-3">
					{#if d.ledger_kind === 'concept'}
						<input aria-label="Usual wording" bind:value={writing[card.id].wording.default}
							class="input-dark input-compact w-full" />
						<input aria-label="Wording when it applies" bind:value={writing[card.id].wording.when_met}
							class="input-dark input-compact w-full" />
					{:else}
						<input aria-label="Wording" bind:value={writing[card.id].wording.text}
							class="input-dark input-compact w-full" />
					{/if}
					{#if problem[card.id]}<p class="text-xs text-amber-300/80">{problem[card.id]}</p>{/if}
					<button type="button" disabled={busy}
						onclick={() => send(d, { choiceId: writing[card.id].choiceId, edited: writing[card.id].wording })}
						class="btn-primary btn-compact">
						Use this wording
					</button>
				</div>
			{:else}
				<div class="flex flex-wrap gap-1.5">
					{#each asDecision(card).choices as c (c.id)}
						<button type="button" disabled={busy} onclick={() => pick(asDecision(card), c.id)}
							class="choice-chip">
							{c.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
