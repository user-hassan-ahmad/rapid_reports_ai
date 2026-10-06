<script lang="ts">
	/**
	 * The review rail (plan Task C4, spec §12.1): tabs Review / Guidelines, an urgency banner, rows grouped by
	 * section ("Unanchored" last; within a section the open action cards come first), one "N to check" group
	 * (collapsed by default), an "Options" group and the "▸ N other checks passed" fold. The legend lives under the
	 * "Report Editor" title, not here; density is fixed to Quiet (the toggle shows only with `devControls`). Below 1100 px it collapses to a strip with the open count that opens as
	 * an overlay. It reads the one item store (lib/review/store.ts) and never changes anything itself: every action
	 * goes out through `onCommand(name, itemId?, args?)`, the same commands the editor popover uses.
	 *
	 * Renders nothing unless the backend reports mode `live` with the rail on, `force` is set (dev page), or `pending`
	 * (the session knows a rail is coming and this report's first GET has not answered): then a fixed-width skeleton,
	 * so nothing shifts when the items arrive. Theme: the app's (dark card, white/10 borders, purple accent).
	 * Assumed normals never appear here; they live only in the editor.
	 *
	 * Chat (plan Task D2, spec §12.5): with `chat`, a composer sits at the foot of the rail. Sending switches the rail
	 * to the thread, headed by a strip "← Review · N open" and "⤢ Expand" (widens the rail). `chatPrefill` ("Ask in
	 * chat") puts text in the composer. Applying a chat edit goes out through `chat.applyEdit`; Undo through
	 * `onCommand('undo')`. A saved thread (`chat.thread`, spec §12.6) opens with the rail; while one exists the head
	 * has "Chat" to return to it.
	 */
	import { untrack, type Snippet } from 'svelte';
	import type { Density } from '../editor/theme';
	import type { ReviewStore } from '../store';
	import type { ReviewItem } from '../types';
	import ItemCard from './ItemCard.svelte';
	import ItemRow, { type RailCommand } from './ItemRow.svelte';
	import ItemTag from './ItemTag.svelte';
	import Legend from './Legend.svelte';
	import ChatThread from './ChatThread.svelte';
	import { compactOpenItems, type RailChat } from '../chat';

	let {
		store,
		onCommand,
		onDensity,
		density = $bindable('quiet'),
		updating = new Set<string>(),
		force = false,
		guidelines,
		urgency = null,
		layout = 'auto',
		theme = 'dark',
		chat,
		chatPrefill = null,
		pending = false,
		devControls = false
	}: {
		store: ReviewStore;
		onCommand: RailCommand;
		onDensity?: (d: Density) => void;
		density?: Density;
		/** Item ids being re-prepared (ProbeLoop state `updating`): their rows show "updating…". */
		updating?: Set<string>;
		/** Render whatever the mode (the dev page). */
		force?: boolean;
		/** The Guidelines tab's content (today's guidelines panel, passed by the viewer). */
		guidelines?: Snippet;
		urgency?: string | null;
		/** `auto` follows the viewport (strip below 1100 px); tests and hosts can pin it. */
		layout?: 'auto' | 'wide' | 'narrow';
		theme?: 'dark' | 'light';
		/** Hosts the chat thread; absent → no composer. */
		chat?: RailChat;
		/** "Ask in chat": the composer takes `text` whenever `seq` changes. */
		chatPrefill?: { text: string; seq: number } | null;
		/** A rail is expected before the store has answered: render the slot with its skeleton. */
		pending?: boolean;
		/** Dev page only: the legend and the density toggle in the rail head. */
		devControls?: boolean;
	} = $props();

	const FINISHED = new Set(['done', 'failed', 'skipped']);

	const stateStore = $derived(store);
	const groupsStore = $derived(store.groups);
	const foldedStore = $derived(store.folded);
	const countsStore = $derived(store.counts);

	const visible = $derived(pending || force || ($stateStore.mode === 'live' && $stateStore.rail));
	const laneStates = $derived(Object.values($stateStore.lanes ?? {}));
	const failed = $derived(
		laneStates.includes('failed') || Object.keys($stateStore.run?.errors ?? {}).length > 0
	);
	const reviewing = $derived(!failed && laneStates.some((v) => !FINISHED.has(v)));
	// Until the first load answers (or while a rail is only expected) the body is a skeleton; while lanes run with
	// nothing to show yet it stays a skeleton too, so a poll never flips it between blank and placeholder.
	const firstLoad = $derived(pending || !$stateStore.loaded);

	const isCheck = (i: ReviewItem) => i.kind === 'check';
	const isOption = (i: ReviewItem) => i.kind === 'option';

	/** Open action cards lead their section; everything else keeps report order (the store's anchor order). */
	const urgentFirst = (items: ReviewItem[]) => {
		const lead = items.filter((i) => variantOf(i) === 'card' && (i.status === 'open' || i.status === 'stale'));
		return lead.length ? [...lead, ...items.filter((i) => !lead.includes(i))] : items;
	};
	const sections = $derived(
		$groupsStore
			.map((g) => ({
				section: g.section,
				items: urgentFirst(g.items.filter((i) => !isCheck(i) && !isOption(i)))
			}))
			.filter((g) => g.items.length > 0)
	);
	const checks = $derived($groupsStore.flatMap((g) => g.items.filter(isCheck)));
	const options = $derived($groupsStore.flatMap((g) => g.items.filter(isOption)));

	let tab = $state<'review' | 'guidelines'>('review');
	let checksOpen = $state(false);
	let foldOpen = $state(false);
	let overlayOpen = $state(false);
	let view = $state<'review' | 'chat'>('review');
	let expanded = $state(false);
	const inChat = $derived(!!chat && view === 'chat');
	/** A thread exists (saved, or sent this session): the head offers "Chat" to go back to it. */
	let hasThread = $state(untrack(() => !!chat?.thread?.length));
	// the rail can mount before its chat (a pending rail): a saved thread arriving later still offers "Chat"
	$effect(() => {
		if (chat?.thread?.length) untrack(() => (hasThread = true));
	});
	const statusOf = (id: string) => $stateStore.items.find((i) => i.id === id)?.status;
	const nothingYet = $derived(!sections.length && !checks.length && !options.length);
	const skeleton = $derived(firstLoad || (reviewing && nothingYet));

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
	const narrow = $derived(layout === 'narrow' || (layout === 'auto' && narrowViewport));

	const variantOf = (i: ReviewItem) =>
		i.status === 'pre_applied'
			? 'preapplied'
			: i.cls === 'action'
				? 'card'
				: i.cls === 'info'
					? 'tag'
					: 'row';

	const foldStatus = (i: ReviewItem) =>
		i.status === 'addressed' ? 'addressed' : i.status === 'dismissed' ? 'dismissed' : 'passed';
</script>

{#snippet itemView(it: ReviewItem)}
	{@const v = variantOf(it)}
	{#if v === 'card'}
		<ItemCard item={it} {onCommand} updating={updating.has(it.id)} />
	{:else if v === 'tag'}
		<ItemTag item={it} {onCommand} updating={updating.has(it.id)} />
	{:else}
		<ItemRow
			item={it}
			{onCommand}
			variant={v === 'preapplied' ? 'preapplied' : 'row'}
			updating={updating.has(it.id)}
		/>
	{/if}
{/snippet}

{#snippet panel()}
	{#if inChat}
		<div class="rv-head rv-chat-head">
			<button type="button" class="rv-btn rv-back" onclick={() => (view = 'review')}
				>← Review · {$countsStore.open} open</button
			>
			<span class="rv-spacer"></span>
			{#if !narrow}
				<button
					type="button"
					class="rv-btn"
					aria-pressed={expanded}
					onclick={() => (expanded = !expanded)}>⤢ Expand</button
				>
			{/if}
		</div>
	{:else}
	<div class="rv-head">
		<div class="rv-tabs-row">
			<div class="rv-tabs" role="tablist" aria-label="Rail">
				<button
					type="button"
					role="tab"
					aria-selected={tab === 'review'}
					onclick={() => (tab = 'review')}>Review</button
				>
				{#if guidelines}
					<button
						type="button"
						role="tab"
						aria-selected={tab === 'guidelines'}
						onclick={() => (tab = 'guidelines')}>Guidelines</button
					>
				{/if}
			</div>
			<span class="rv-spacer"></span>
			{#if chat && hasThread}
				<button type="button" class="rv-btn" onclick={() => (view = 'chat')}>Chat</button>
			{/if}
			<button
				type="button"
				class="rv-btn"
				disabled={reviewing || firstLoad}
				title="Run the full review again on the current report"
				onclick={() => onCommand('rerun')}>Re-review</button
			>
		</div>
		{#if urgency}
			<div class="rv-urgency" role="alert"><span aria-hidden="true">!</span> {urgency}</div>
		{/if}
		{#if devControls && tab === 'review'}
			<Legend bind:density {onDensity} showDensity />
		{/if}
		{#if tab === 'review'}
			<!-- one fixed-height line: Reviewing… / Review incomplete / the open count, never a jump -->
			<div class="rv-status" role="status" aria-live="polite">
				{#if failed}
					<span class="rv-incomplete"><span aria-hidden="true">⚠</span> Review incomplete</span>
				{:else if firstLoad || reviewing}
					<span class="rv-pulse" aria-hidden="true"></span><span>Reviewing…</span>
				{:else if $countsStore.open}
					<span>{$countsStore.open} to review</span>
				{:else}
					<span>All reviewed</span>
				{/if}
			</div>
		{/if}
	</div>

	{/if}

	{#if inChat}
		<!-- the thread renders inside ChatThread below -->
	{:else if tab === 'guidelines' && guidelines}
		<div class="rv-body" role="tabpanel" aria-label="Guidelines">{@render guidelines()}</div>
	{:else}
		<div class="rv-body" role="tabpanel" aria-label="Review">
			{#if skeleton}
				<div data-testid="rv-skeleton" aria-label="Loading review" aria-busy="true">
					{#each [0, 1, 2] as n (n)}
						<div class="rv-skel-card">
							<div class="rv-skel rv-skel-title"></div>
							<div class="rv-skel"></div>
							<div class="rv-skel rv-skel-short"></div>
						</div>
					{/each}
				</div>
			{:else}
				{#each sections as g (g.section)}
					<section class="rv-group">
						<h3 class="rv-group-title" data-rv-section={g.section}>{g.section}</h3>
						{#each g.items as it (it.id)}{@render itemView(it)}{/each}
					</section>
				{/each}

				{#if checks.length}
					<section class="rv-group rv-checks" data-rv-group="checks">
						<button
							type="button"
							class="rv-group-toggle"
							aria-expanded={checksOpen}
							onclick={() => (checksOpen = !checksOpen)}
						>
							<span aria-hidden="true">{checksOpen ? '▾' : '▸'}</span>
							{checks.length} to check
						</button>
						{#if checksOpen}
							{#each checks as it (it.id)}
								<ItemRow item={it} {onCommand} variant="check" updating={updating.has(it.id)} />
							{/each}
						{/if}
					</section>
				{/if}

				{#if options.length}
					<section class="rv-group" data-rv-group="options">
						<h3 class="rv-group-title">Options</h3>
						{#each options as it (it.id)}
							<ItemRow item={it} {onCommand} variant="option" updating={updating.has(it.id)} />
						{/each}
					</section>
				{/if}

				{#if $foldedStore.length}
					<section class="rv-group rv-fold" data-rv-group="folded">
						<button
							type="button"
							class="rv-group-toggle"
							aria-expanded={foldOpen}
							onclick={() => (foldOpen = !foldOpen)}
						>
							<span aria-hidden="true">{foldOpen ? '▾' : '▸'}</span>
							{$foldedStore.length} other checks passed
						</button>
						{#if foldOpen}
							<ul class="rv-fold-list">
								{#each $foldedStore as it (it.id)}
									<li data-rv-folded={it.id}>
										<span aria-hidden="true">✓</span>
										{it.label || it.kind} <span class="rv-muted">· {foldStatus(it)}</span>
									</li>
								{/each}
							</ul>
						{/if}
					</section>
				{/if}

				{#if nothingYet && !reviewing && !failed}
					<p class="rv-muted rv-empty">Nothing to review.</p>
				{/if}
			{/if}
		</div>
	{/if}
	{#if chat}
		<ChatThread
			reportId={chat.reportId}
			getText={chat.getText}
			openItems={() => compactOpenItems($stateStore.items)}
			applyEdit={chat.applyEdit}
			undoEdit={(id) => onCommand('undo', id)}
			{statusOf}
			showThread={inChat}
			onSent={() => {
				view = 'chat';
				hasThread = true;
			}}
			prefill={chatPrefill}
			thread={chat.thread}
		/>
	{/if}
{/snippet}

{#if visible}
	<aside
		class="rv-rail"
		class:rv-narrow={narrow}
		class:rv-expanded={inChat && expanded && !narrow}
		data-theme={theme}
		data-testid="review-rail"
		aria-label="Review"
	>
		{#if narrow}
			<button
				type="button"
				class="rv-strip"
				aria-expanded={overlayOpen}
				aria-label={`Review: ${$countsStore.open} open`}
				onclick={() => (overlayOpen = !overlayOpen)}
			>
				<span class="rv-strip-count">{$countsStore.open}</span>
				<span>open</span>
				{#if reviewing}<span class="rv-muted">…</span>{/if}
				{#if failed}<span aria-hidden="true">⚠</span>{/if}
			</button>
			{#if overlayOpen}
				<div class="rv-overlay" role="dialog" aria-label="Review">
					<button
						type="button"
						class="rv-btn rv-close"
						aria-label="Close review"
						onclick={() => (overlayOpen = false)}>×</button
					>
					{@render panel()}
				</div>
			{/if}
		{:else}
			{@render panel()}
		{/if}
	</aside>
{/if}

<style>
	/* The app's look (app.css card-dark / btn-sm, the Report Editor card's segmented control): a dark glass panel
	   with white/10 borders, rounded-lg, gray-200 text, purple-600 accent. Mark colours match the editor marks
	   (editor/theme.ts) so a rail icon and its underline read the same. The app is dark-only; `light` exists for
	   the dev page and follows the same structure. */
	.rv-rail {
		--rv-surface: rgba(255, 255, 255, 0.03);
		--rv-surface-hover: rgba(255, 255, 255, 0.07);
		--rv-panel: rgba(255, 255, 255, 0.02);
		--rv-overlay: rgba(6, 6, 10, 0.98);
		--rv-text: #e5e7eb;
		--rv-muted: #9ca3af;
		--rv-border: rgba(255, 255, 255, 0.1);
		--rv-border-strong: rgba(255, 255, 255, 0.2);
		--rv-accent: #9333ea;
		--rv-accent-hover: #a855f7;
		--rv-accent-soft: rgba(147, 51, 234, 0.15);
		--rv-focus: #a855f7;
		--rv-segment: rgba(31, 41, 55, 0.6);
		--rv-green-line: #5cc285;
		--rv-amber-line: #e3a94a;
		--rv-amber-bg: rgba(227, 169, 74, 0.12);
		--rv-red-line: #ff7a7a;
		--rv-red-bg: rgba(239, 68, 68, 0.1);
		--rv-blue-line: #7ea6f0;
		--rv-del: #ff8c80;
		--rv-ins: #6fd394;
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
	.rv-rail[data-theme='light'] {
		--rv-surface: #ffffff;
		--rv-surface-hover: #f5f3ff;
		--rv-panel: #fafafa;
		--rv-overlay: #ffffff;
		--rv-text: #1f2937;
		--rv-muted: #6b7280;
		--rv-border: #e5e7eb;
		--rv-border-strong: #d1d5db;
		--rv-accent: #9333ea;
		--rv-accent-hover: #7e22ce;
		--rv-accent-soft: rgba(147, 51, 234, 0.1);
		--rv-focus: #9333ea;
		--rv-segment: #f3f4f6;
		--rv-green-line: #3f9a5d;
		--rv-amber-line: #b7791f;
		--rv-amber-bg: #fcebc7;
		--rv-red-line: #cf3b3b;
		--rv-red-bg: #fde2e2;
		--rv-blue-line: #3b6fcf;
		--rv-del: #b42318;
		--rv-ins: #1f7a3f;
	}
	.rv-rail.rv-expanded {
		width: 560px;
		min-width: 560px;
		max-width: 560px;
	}
	.rv-chat-head {
		flex-direction: row;
		align-items: center;
	}
	.rv-rail.rv-narrow {
		width: auto;
		min-width: 0;
		max-width: none;
		border: 0;
		border-radius: 0;
		background: transparent;
	}
	.rv-head {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px 12px 8px;
		border-bottom: 1px solid var(--rv-border);
		flex: none;
	}
	.rv-tabs-row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	/* the Report Editor card's Report / History segmented control */
	.rv-tabs {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px;
		border-radius: 0.5rem;
		background: var(--rv-segment);
	}
	.rv-tabs [role='tab'] {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 500;
		background: none;
		border: 0;
		border-radius: 0.375rem;
		padding: 4px 10px;
		color: #d1d5db;
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
	}
	.rv-rail[data-theme='light'] .rv-tabs [role='tab'] {
		color: var(--rv-muted);
	}
	.rv-tabs [role='tab']:hover {
		color: #fff;
	}
	.rv-tabs [role='tab'][aria-selected='true'] {
		background: var(--rv-accent);
		color: #fff;
	}
	.rv-spacer {
		flex: 1;
	}
	.rv-urgency {
		border: 1px solid var(--rv-red-line);
		background: var(--rv-red-bg);
		color: var(--rv-text);
		border-radius: 0.5rem;
		padding: 6px 10px;
		font-weight: 600;
		font-size: 0.75rem;
	}
	.rv-status {
		display: flex;
		align-items: center;
		gap: 6px;
		height: 18px;
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.rv-pulse {
		width: 6px;
		height: 6px;
		border-radius: 9999px;
		background: var(--rv-accent-hover);
		animation: rv-pulse 1.6s ease-in-out infinite;
	}
	@keyframes rv-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}
	.rv-incomplete {
		color: var(--rv-amber-line);
		font-weight: 600;
	}
	.rv-body {
		overflow-y: auto;
		padding: 8px 12px 12px;
		flex: 1;
		min-height: 0;
	}
	.rv-group {
		margin-bottom: 12px;
	}
	.rv-group-title {
		font-size: 0.6875rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--rv-muted);
		margin: 8px 0 4px;
		font-weight: 600;
	}
	.rv-group-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font: inherit;
		font-size: 0.75rem;
		font-weight: 600;
		background: none;
		border: 0;
		border-radius: 0.375rem;
		padding: 3px 6px 3px 2px;
		color: var(--rv-text);
		cursor: pointer;
	}
	.rv-group-toggle:hover {
		background: var(--rv-surface-hover);
	}
	.rv-checks {
		border-left: 2px dashed var(--rv-amber-line);
		padding-left: 8px;
	}
	.rv-fold-list {
		list-style: none;
		margin: 2px 0 0;
		padding: 0 0 0 16px;
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.rv-muted {
		color: var(--rv-muted);
	}
	.rv-empty {
		font-size: 0.8125rem;
		padding: 12px 0;
		text-align: center;
	}
	.rv-skel-card {
		border: 1px solid var(--rv-border);
		border-radius: 0.5rem;
		padding: 10px 12px;
		margin: 6px 0 8px;
		background: var(--rv-surface);
	}
	.rv-skel {
		height: 10px;
		margin: 6px 0;
		border-radius: 4px;
		background: var(--rv-surface-hover);
		animation: rv-pulse 1.6s ease-in-out infinite;
	}
	.rv-skel-title {
		width: 60%;
		height: 12px;
	}
	.rv-skel-short {
		width: 40%;
	}
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
	.rv-btn:hover:not(:disabled) {
		background: var(--rv-surface-hover);
		border-color: var(--rv-border-strong);
	}
	.rv-btn:disabled {
		opacity: 0.5;
		cursor: default;
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
	.rv-close {
		align-self: flex-end;
		margin: 6px 8px 0;
	}
	button:focus-visible {
		outline: 2px solid var(--rv-focus);
		outline-offset: 1px;
	}
</style>
