<script lang="ts">
	/**
	 * The review rail (plan Task C4, spec §12.1): tabs Review / Guidelines, an urgency banner, the legend with a
	 * density toggle, rows grouped by section ("Unanchored" last), one "N to check" group, an "Options" group and
	 * the "▸ N other checks passed" fold. Below 1100 px it collapses to a strip with the open count that opens as
	 * an overlay. It reads the one item store (lib/review/store.ts) and never changes anything itself: every action
	 * goes out through `onCommand(name, itemId?, args?)`, the same commands the editor popover uses.
	 *
	 * Renders nothing unless the backend reports mode `live` with the rail on, or `force` is set (dev page).
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
		chatPrefill = null
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
	} = $props();

	const FINISHED = new Set(['done', 'failed', 'skipped']);

	const stateStore = $derived(store);
	const groupsStore = $derived(store.groups);
	const foldedStore = $derived(store.folded);
	const countsStore = $derived(store.counts);

	const visible = $derived(force || ($stateStore.mode === 'live' && $stateStore.rail));
	const laneStates = $derived(Object.values($stateStore.lanes ?? {}));
	const failed = $derived(
		laneStates.includes('failed') || Object.keys($stateStore.run?.errors ?? {}).length > 0
	);
	const reviewing = $derived(!failed && laneStates.some((v) => !FINISHED.has(v)));
	const skeleton = $derived($stateStore.loading && $stateStore.items.length === 0);

	const isCheck = (i: ReviewItem) => i.kind === 'check';
	const isOption = (i: ReviewItem) => i.kind === 'option';

	const sections = $derived(
		$groupsStore
			.map((g) => ({
				section: g.section,
				items: g.items.filter((i) => !isCheck(i) && !isOption(i))
			}))
			.filter((g) => g.items.length > 0)
	);
	const checks = $derived($groupsStore.flatMap((g) => g.items.filter(isCheck)));
	const options = $derived($groupsStore.flatMap((g) => g.items.filter(isOption)));

	let tab = $state<'review' | 'guidelines'>('review');
	let checksOpen = $state(true);
	let foldOpen = $state(false);
	let overlayOpen = $state(false);
	let view = $state<'review' | 'chat'>('review');
	let expanded = $state(false);
	const inChat = $derived(!!chat && view === 'chat');
	/** A thread exists (saved, or sent this session): the head offers "Chat" to go back to it. */
	let hasThread = $state(untrack(() => !!chat?.thread?.length));
	const statusOf = (id: string) => $stateStore.items.find((i) => i.id === id)?.status;

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
			<span class="rv-spacer"></span>
			{#if chat && hasThread}
				<button type="button" class="rv-btn" onclick={() => (view = 'chat')}>Chat</button>
			{/if}
			<button
				type="button"
				class="rv-btn"
				disabled={reviewing}
				title="Run the full review again on the current report"
				onclick={() => onCommand('rerun')}>Re-review</button
			>
		</div>
		{#if urgency}
			<div class="rv-urgency" role="alert"><span aria-hidden="true">!</span> {urgency}</div>
		{/if}
		{#if tab === 'review'}
			<Legend bind:density {onDensity} />
			<div class="rv-status" role="status" aria-live="polite">
				{#if failed}
					<span class="rv-incomplete"><span aria-hidden="true">⚠</span> Review incomplete</span>
				{:else if reviewing}
					<span>Reviewing…</span>
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
					{#each [0, 1, 2, 3] as n (n)}<div class="rv-skel"></div>{/each}
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

				{#if !sections.length && !checks.length && !options.length && !reviewing && !failed}
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
	.rv-rail {
		--rv-surface: #1e2125;
		--rv-surface-hover: #292d32;
		--rv-text: #e6e8eb;
		--rv-muted: #a0a7b1;
		--rv-border: #3a3f46;
		--rv-green-line: #5cc285;
		--rv-amber-line: #e3a94a;
		--rv-amber-bg: #43341a;
		--rv-red-line: #ff7a7a;
		--rv-red-bg: #4a2222;
		--rv-blue-line: #7ea6f0;
		--rv-del: #ff8c80;
		--rv-ins: #6fd394;
		display: flex;
		flex-direction: column;
		width: 340px;
		max-height: 100%;
		background: var(--rv-surface);
		color: var(--rv-text);
		border-left: 1px solid var(--rv-border);
		font-size: 0.85rem;
	}
	.rv-rail[data-theme='light'] {
		--rv-surface: #ffffff;
		--rv-surface-hover: #f0f0ec;
		--rv-text: #1f2328;
		--rv-muted: #5f6670;
		--rv-border: #d6d8db;
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
	}
	.rv-chat-head {
		flex-direction: row;
		align-items: center;
	}
	.rv-rail.rv-narrow {
		width: auto;
		border-left: 0;
	}
	.rv-head {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 8px 10px;
		border-bottom: 1px solid var(--rv-border);
	}
	.rv-tabs {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.rv-tabs [role='tab'] {
		font: inherit;
		background: none;
		border: 0;
		border-bottom: 2px solid transparent;
		padding: 2px 6px;
		color: var(--rv-muted);
		cursor: pointer;
	}
	.rv-tabs [role='tab'][aria-selected='true'] {
		color: var(--rv-text);
		border-bottom-color: var(--rv-text);
		font-weight: 600;
	}
	.rv-spacer {
		flex: 1;
	}
	.rv-urgency {
		border: 1px solid var(--rv-red-line);
		background: var(--rv-red-bg);
		border-radius: 6px;
		padding: 6px 8px;
		font-weight: 600;
	}
	.rv-status {
		font-size: 0.75rem;
		color: var(--rv-muted);
		min-height: 1em;
	}
	.rv-incomplete {
		color: var(--rv-amber-line);
		font-weight: 600;
	}
	.rv-body {
		overflow-y: auto;
		padding: 6px 10px 12px;
		flex: 1;
	}
	.rv-group {
		margin-bottom: 10px;
	}
	.rv-group-title {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--rv-muted);
		margin: 6px 0 2px;
		font-weight: 600;
	}
	.rv-group-toggle {
		font: inherit;
		font-size: 0.78rem;
		font-weight: 600;
		background: none;
		border: 0;
		padding: 2px 0;
		color: var(--rv-text);
		cursor: pointer;
	}
	.rv-checks {
		border-left: 2px dashed var(--rv-amber-line);
		padding-left: 6px;
	}
	.rv-fold-list {
		list-style: none;
		margin: 2px 0 0;
		padding: 0 0 0 14px;
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.rv-muted {
		color: var(--rv-muted);
	}
	.rv-empty {
		font-size: 0.8rem;
	}
	.rv-skel {
		height: 14px;
		margin: 8px 0;
		border-radius: 4px;
		background: var(--rv-surface-hover);
	}
	.rv-btn {
		font: inherit;
		font-size: 0.75rem;
		padding: 0 8px;
		line-height: 1.7;
		border-radius: 9px;
		border: 1px solid var(--rv-border);
		background: var(--rv-surface);
		color: var(--rv-text);
		cursor: pointer;
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
		background: var(--rv-surface);
		color: var(--rv-text);
		border: 0;
		border-left: 1px solid var(--rv-border);
		cursor: pointer;
		height: 100%;
	}
	.rv-strip-count {
		font-size: 1rem;
		font-weight: 700;
	}
	.rv-overlay {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: min(360px, 100vw);
		display: flex;
		flex-direction: column;
		background: var(--rv-surface);
		border-left: 1px solid var(--rv-border);
		box-shadow: -8px 0 24px rgba(0, 0, 0, 0.35);
		z-index: 50;
	}
	.rv-close {
		align-self: flex-end;
		margin: 6px 8px 0;
	}
	button:focus-visible {
		outline: 2px solid var(--rv-blue-line);
		outline-offset: 1px;
	}
</style>
