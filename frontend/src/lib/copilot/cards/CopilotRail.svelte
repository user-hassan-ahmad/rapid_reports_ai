<script lang="ts">
	/** The scratchpad Copilot rail: the shared RailFrame with one "Guidelines" tab over CopilotCards. Below 1100 px
	 *  it is the strip "<n> guidelines" that opens the same panel as an overlay. Presentational, like the cards. */
	import type { ComponentProps } from 'svelte';
	import RailFrame from '$lib/rail/RailFrame.svelte';
	import RailTabs from '$lib/rail/RailTabs.svelte';
	import CopilotCards from './CopilotCards.svelte';

	type CardsProps = ComponentProps<typeof CopilotCards>;
	let {
		theme = 'dark',
		layout = 'auto',
		...cards
	}: CardsProps & { theme?: 'dark' | 'light'; layout?: 'auto' | 'wide' | 'narrow' } = $props();

	const tabs = [{ id: 'guidelines' as const, label: 'Guidelines' }];
	let tab = $state<'guidelines'>('guidelines');
	const count = $derived(cards.groups.reduce((n, g) => n + g.cards.length, 0));
</script>

{#snippet head()}
	<div class="rv-head">
		<RailTabs {tabs} bind:active={tab} ariaLabel="Copilot" />
	</div>
{/snippet}

{#snippet body()}
	<div class="rv-body" role="tabpanel" aria-label="Guidelines">
		<CopilotCards {...cards} />
	</div>
{/snippet}

<RailFrame {theme} {layout} ariaLabel="Copilot" testid="copilot-rail" stripLabel={count === 1 ? 'guideline' : 'guidelines'} stripCount={count} {head} {body} />
