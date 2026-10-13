<script lang="ts">
	// One-tap cards inside the refine chat (chat-edit router spec, "Uncertain or rejected changes become cards"): the
	// Rules step's decision cards (prefilled, nothing pre-selected) and the router's proposal cards. Nothing is applied
	// until a tap; the parent posts the answer to /skill-sheet/refine/card.
	import { changeFor, editWording, wordingProblem, type Answer } from '$lib/template-rules/cards';
	import type { CardWording, DecisionCard } from '$lib/template-rules/types';
	import { isProposal, type CardAnswer, type ProposalCard, type RouterCard } from './types';

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

<div class="space-y-2">
	{#each cards as card (card.id)}
		<div class="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-gray-200">
			<p>{card.title}</p>
			{#if done[card.id]}
				<p class="text-xs text-gray-400 mt-1">{done[card.id]}</p>
			{:else if isProposal(card)}
				<div class="flex gap-2 mt-2">
					<button type="button" disabled={busy} onclick={() => apply(asProposal(card))}
						class="px-2.5 py-1 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-xs disabled:opacity-40">
						Apply
					</button>
					<button type="button" disabled={busy} onclick={() => (done[card.id] = 'Left as is')}
						class="px-2.5 py-1 rounded-md bg-white/[0.04] border border-white/10 text-gray-400 text-xs disabled:opacity-40">
						Leave as is
					</button>
				</div>
			{:else if writing[card.id]}
				{@const d = asDecision(card)}
				<div class="mt-2 space-y-2">
					{#if d.ledger_kind === 'concept'}
						<input aria-label="Usual wording" bind:value={writing[card.id].wording.default}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
						<input aria-label="Wording when it applies" bind:value={writing[card.id].wording.when_met}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
					{:else}
						<input aria-label="Wording" bind:value={writing[card.id].wording.text}
							class="w-full rounded-md bg-white/[0.04] border border-white/10 px-2 py-1 text-xs text-gray-200" />
					{/if}
					{#if problem[card.id]}<p class="text-xs text-amber-300">{problem[card.id]}</p>{/if}
					<button type="button" disabled={busy}
						onclick={() => send(d, { choiceId: writing[card.id].choiceId, edited: writing[card.id].wording })}
						class="px-2.5 py-1 rounded-md bg-purple-500/15 border border-purple-500/30 text-purple-200 text-xs disabled:opacity-40">
						Use this wording
					</button>
				</div>
			{:else}
				<div class="flex flex-wrap gap-2 mt-2">
					{#each asDecision(card).choices as c (c.id)}
						<button type="button" disabled={busy} onclick={() => pick(asDecision(card), c.id)}
							class="px-2.5 py-1 rounded-md bg-white/[0.04] border border-white/10 text-gray-300 text-xs hover:border-purple-500/40 disabled:opacity-40">
							{c.label}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
