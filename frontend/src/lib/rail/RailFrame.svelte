<script lang="ts">
	/**
	 * The rail's frame, shared by the post-generation review rail and the scratchpad Copilot: a 340 px `<aside>`
	 * with the `--rv-*` theme tokens (rail.css). Below 1100 px it collapses to a strip ("N open") that opens the
	 * same head and body as a fixed overlay; `layout` pins either form. The host owns everything inside `head`
	 * and `body` (each gets `{ narrow }` so it can render for the current form on the first frame).
	 */
	import type { Snippet } from 'svelte';
	import './rail.css';

	type Ctx = { narrow: boolean };

	let {
		theme = 'dark',
		layout = 'auto',
		ariaLabel,
		testid,
		stripLabel,
		stripCount,
		stripExtra,
		expanded = false,
		narrow = $bindable(false),
		overlayOpen = $bindable(false),
		el = $bindable(null),
		head,
		body
	}: {
		theme?: 'dark' | 'light';
		/** `auto` follows the viewport (strip below 1100 px); tests and hosts can pin it. */
		layout?: 'auto' | 'wide' | 'narrow';
		/** Names the rail, the overlay dialog and (with the count) the strip, e.g. "Review" → "Review: 2 open". */
		ariaLabel: string;
		testid?: string;
		/** The narrow strip's text under the count, e.g. "open". */
		stripLabel: string;
		stripCount: number;
		/** Extra marks on the strip after the label (e.g. a running or failed sign). */
		stripExtra?: Snippet;
		/** Widen the wide rail (560 px); ignored when narrow. */
		expanded?: boolean;
		/** Read-out: the rail is currently a strip. */
		narrow?: boolean;
		/** The narrow overlay is open; hosts open it to reveal something. */
		overlayOpen?: boolean;
		/** Read-out: the `<aside>` element. */
		el?: HTMLElement | null;
		head?: Snippet<[Ctx]>;
		body?: Snippet<[Ctx]>;
	} = $props();

	// Below ~1100 px the rail is a strip; `layout` pins it either way.
	let narrowViewport = $state(false);
	$effect(() => {
		if (layout !== 'auto' || typeof window === 'undefined' || !window.matchMedia) return;
		const mq = window.matchMedia('(max-width: 1099.98px)');
		narrowViewport = mq.matches;
		const on = (e: MediaQueryListEvent) => (narrowViewport = e.matches);
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});
	const isNarrow = $derived(layout === 'narrow' || (layout === 'auto' && narrowViewport));
	$effect.pre(() => {
		narrow = isNarrow;
	});
</script>

{#snippet panel()}
	{@render head?.({ narrow: isNarrow })}
	{@render body?.({ narrow: isNarrow })}
{/snippet}

<aside
	class="rv-rail"
	class:rv-narrow={isNarrow}
	class:rv-expanded={expanded && !isNarrow}
	data-theme={theme}
	bind:this={el}
	data-testid={testid}
	aria-label={ariaLabel}
>
	{#if isNarrow}
		<button
			type="button"
			class="rv-strip"
			aria-expanded={overlayOpen}
			aria-label={`${ariaLabel}: ${stripCount} ${stripLabel}`}
			onclick={() => (overlayOpen = !overlayOpen)}
		>
			<span class="rv-strip-count">{stripCount}</span>
			<span>{stripLabel}</span>
			{@render stripExtra?.()}
		</button>
		{#if overlayOpen}
			<div class="rv-overlay" role="dialog" aria-label={ariaLabel}>
				<button
					type="button"
					class="rv-btn rv-close"
					aria-label={`Close ${ariaLabel.toLowerCase()}`}
					onclick={() => (overlayOpen = false)}>×</button
				>
				{@render panel()}
			</div>
		{/if}
	{:else}
		{@render panel()}
	{/if}
</aside>

<style>
	.rv-rail {
		display: flex;
		flex-direction: column;
		flex: none;
		width: 340px;
		min-width: 340px;
		max-width: 340px;
		height: 100%;
		max-height: 100%;
		box-sizing: border-box;
		background: var(--rv-panel);
		color: var(--rv-text);
		border: 1px solid var(--rv-border);
		border-radius: 0.5rem;
		overflow: hidden;
		font-family: 'DM Sans', 'IBM Plex Sans', system-ui, sans-serif;
		font-size: 0.8125rem;
		line-height: 1.45;
	}
	.rv-rail.rv-expanded {
		width: 560px;
		min-width: 560px;
		max-width: 560px;
	}
	.rv-rail.rv-narrow {
		width: auto;
		min-width: 0;
		max-width: none;
		border: 0;
		border-radius: 0;
		background: transparent;
	}
	.rv-strip {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		width: 44px;
		padding: 8px 0;
		font: inherit;
		font-size: 0.72rem;
		background: var(--rv-panel);
		color: var(--rv-text);
		border: 1px solid var(--rv-border);
		border-radius: 0.5rem;
		cursor: pointer;
		height: 100%;
	}
	.rv-strip-count {
		font-size: 1rem;
		font-weight: 700;
		color: var(--rv-accent-hover);
	}
	.rv-overlay {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: min(360px, 100vw);
		display: flex;
		flex-direction: column;
		background: var(--rv-overlay);
		border-left: 1px solid var(--rv-border);
		box-shadow: -8px 0 24px rgba(0, 0, 0, 0.45);
		z-index: 50;
	}
	/* the close button matches the hosts' .rv-btn */
	.rv-btn {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 500;
		padding: 3px 10px;
		line-height: 1.4;
		border-radius: 0.375rem;
		border: 1px solid var(--rv-border);
		background: var(--rv-surface);
		color: var(--rv-text);
		cursor: pointer;
		transition: background-color 0.15s, border-color 0.15s;
	}
	.rv-btn:hover {
		background: var(--rv-surface-hover);
		border-color: var(--rv-border-strong);
	}
	.rv-close {
		align-self: flex-end;
		margin: 6px 8px 0;
	}
	/* a revealed card (the editor chip's "›") glows purple, then settles */
	@keyframes rv-reveal {
		0%,
		60% {
			box-shadow: 0 0 0 2px var(--rv-accent-hover);
			background-color: var(--rv-accent-soft);
		}
		100% {
			box-shadow: 0 0 0 0 transparent;
		}
	}
	.rv-rail :global(.rv-revealed) {
		animation: rv-reveal 1.5s ease-out;
		border-radius: 0.5rem;
	}
	button:focus-visible {
		outline: 2px solid var(--rv-focus);
		outline-offset: 1px;
	}
</style>
