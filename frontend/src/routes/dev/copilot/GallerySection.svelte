<script lang="ts">
	/** One gallery section with local, fake session behaviour (no backend): open and close toggle view.open, retries
	 *  resolve after a short delay, "Other guidelines" adds the section's `others`. SYNTHETIC data only. */
	import { untrack } from 'svelte';
	import CopilotCards from '$lib/copilot/cards/CopilotCards.svelte';
	import CopilotRail from '$lib/copilot/cards/CopilotRail.svelte';
	import { closedView, type CardView } from '$lib/copilot/cards/view';
	import { cardRef, norm, type Group } from '$lib/copilot/state';
	import type { Section } from './gallery';

	let { section, rail = null, theme = 'dark' }: { section: Section; rail?: 'wide' | 'narrow' | null; theme?: 'dark' | 'light' } = $props();
	const init = untrack(() => section);
	let groups = $state<Group[]>(structuredClone(init.groups));
	let views = $state<Record<string, CardView>>(structuredClone(init.views));
	let matching = $state(!!init.matching);
	let matchFailed = $state(!!init.matchFailed);
	let otherState = $state(init.otherState ?? 'idle');
	const later = (fn: () => void) => setTimeout(fn, 600);
	const patch = (ref: string, p: Partial<CardView>) => {
		views[ref] = { ...(views[ref] ?? closedView), ...p };
	};

	const handlers = {
		onOpen: (ref: string) => patch(ref, { open: true }),
		onClose: (ref: string) => patch(ref, { open: false }),
		onRetry: (ref: string) => {
			const base = ref.split('#')[0];
			const was = views[base]?.error;
			patch(base, { loading: true, error: null });
			later(() => patch(base, { loading: false, error: was === 'loading' ? null : 'timeout' }));
		},
		onRetryMatch: () => {
			matchFailed = false;
			matching = true;
			later(() => (matching = false));
		},
		onOther: () => {
			otherState = 'loading';
			later(() => {
				if (!init.others) return (otherState = init.otherState === 'failed' ? 'failed' : 'done');
				for (const o of init.others) {
					const g = groups.find((x) => x.finding && norm(x.finding.text) === norm(o.card.finding));
					if (!g) continue;
					g.cards = [...g.cards, o.card];
					views[cardRef(o.card)] = { ...closedView, fromOther: true, result: o.result, error: o.error ?? null };
				}
				otherState = 'done';
			});
		}
	};
</script>

{#if rail}
	<div class="dv-rail-row" class:narrow={rail === 'narrow'}>
		<div class="dv-pad">Scratchpad (stand-in)</div>
		<CopilotRail layout={rail} {theme} {groups} {views} {matching} {matchFailed} {otherState} {...handlers} />
	</div>
{:else}
	<section class="dv-section" data-testid="dv-{section.id}" aria-label={section.title}>
		<h2>{section.title}</h2>
		<div class="rv-rail dv-col" data-theme={theme}>
			<CopilotCards {groups} {views} {matching} {matchFailed} {otherState} {...handlers} />
		</div>
	</section>
{/if}

<style>
	.dv-section h2 {
		font-size: 0.75rem;
		font-weight: 600;
		color: #9ca3af;
		margin: 0 0 6px;
	}
	.dv-col {
		background: var(--rv-panel);
		color: var(--rv-text);
		width: 420px; /* the Copilot rail's width (B0) */
		box-sizing: border-box;
		padding: 10px 12px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
	}
	.dv-rail-row {
		display: flex;
		width: 900px;
		gap: 12px;
		height: 640px;
	}
	.dv-rail-row.narrow {
		width: 520px;
	}
	.dv-pad {
		flex: 1;
		min-width: 120px;
		overflow: hidden;
		padding: 12px;
		border: 1px dashed rgba(255, 255, 255, 0.15);
		border-radius: 0.5rem;
		color: #6b7280;
		font-size: 0.8125rem;
	}
</style>
