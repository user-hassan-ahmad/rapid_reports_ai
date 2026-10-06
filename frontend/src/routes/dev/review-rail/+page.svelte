<script lang="ts">
	/**
	 * /dev/review-rail (Plan 3 C7): a dev-only page (guarded in +page.ts) for rail development and the Gate F hand
	 * read. Pick one of your recent reports (or paste an id); the page loads its text and its latest review run and
	 * renders the editor with the review marks beside the rail, forced on even for a shadow run.
	 *
	 * Commands apply locally. Nothing reaches the server unless "Post events" is on: then item events post through
	 * the store and Re-review asks for a fresh run. The wiring follows ReportResponseViewer (one command → one editor
	 * transaction, items synced into the editor field after a tick), minus the probe loop, workspace and chat.
	 */
	import { onDestroy, onMount, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { EditorView } from '@codemirror/view';
	import type { Extension } from '@codemirror/state';
	import { API_URL } from '$lib/config.js';
	import { token } from '$lib/stores/auth.js';
	import { getReview } from '$lib/review/api';
	import ReportEditor from '../../components/ReportEditor.svelte';
	import ReviewRail from '$lib/review/rail/ReviewRail.svelte';
	import { createReviewStore, type ReviewStore } from '$lib/review/store';
	import { runCommand, type CommandName, type ItemEvent } from '$lib/review/commands';
	import { reviewExtensions, setDensity, type Density } from '$lib/review/editor';
	import {
		commandTransaction,
		syncItems,
		widgetPosOf,
		type ReviewHistoryEvent
	} from '$lib/review/editor/field';
	import { textHash } from '$lib/review/hash';
	import type { ItemStatus, ReviewItem, UserCommand } from '$lib/review/types';

	interface ReportRow {
		id: string;
		description?: string | null;
		report_type?: string | null;
		created_at?: string;
		report_content?: string | null;
	}

	const USER_COMMANDS = new Set<string>(['apply', 'edit', 'undo', 'dismiss', 'restore', 'view', 'ask_chat']);
	const RECENT = 20;

	let reports = $state<ReportRow[]>([]);
	let listError = $state<string | null>(null);
	let listLoading = $state(false);
	/** Report id → the latest run's mode ('shadow' / 'live' …), or null when the report has no run. */
	let runs = $state<Record<string, string | null>>({});
	let pasted = $state('');
	let postEvents = $state(false);

	let reportId = $state<string | null>(null);
	let text = $state<string | null>(null);
	let loadError = $state<string | null>(null);
	let store = $state<ReviewStore | null>(null);
	let extensions = $state<Extension[]>([]);
	let density = $state<Density>('quiet');
	let editorRef = $state<{ getView(): EditorView | null } | null>(null);
	let unsubscribe: (() => void) | null = null;
	let syncQueued = false;
	let postChain: Promise<unknown> = Promise.resolve();

	const run = $derived($store?.run ?? null);

	async function api<T>(path: string): Promise<T> {
		const res = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${get(token)}` } });
		const data = await res.json().catch(() => null);
		if (!res.ok || !data?.success) throw new Error(data?.error || `request failed (${res.status})`);
		return data as T;
	}

	async function loadReports(): Promise<void> {
		listLoading = true;
		listError = null;
		try {
			const data = await api<{ reports: ReportRow[] }>(`/api/reports?limit=${RECENT}`);
			reports = data.reports.slice(0, RECENT);
			// which of them have a review run (the list endpoint does not say)
			await Promise.all(
				reports.map(async (r) => {
					try {
						const rv = await getReview(r.id);
						runs[r.id] = rv.run ? rv.run.mode : null;
					} catch {
						runs[r.id] = null;
					}
				})
			);
		} catch (e) {
			listError = e instanceof Error ? e.message : String(e);
		} finally {
			listLoading = false;
		}
	}

	function teardown(): void {
		store?.stopPolling();
		unsubscribe?.();
		unsubscribe = null;
		store = null;
		extensions = [];
		text = null;
	}

	async function openReport(id: string): Promise<void> {
		id = id.trim();
		if (!id) return;
		teardown();
		reportId = id;
		loadError = null;
		try {
			const data = await api<{ report: ReportRow & { final_report_content?: string | null } }>(
				`/api/reports/${encodeURIComponent(id)}`
			);
			if (reportId !== id) return;
			const s = createReviewStore(id);
			await s.load();
			if (reportId !== id) return;
			const st = get(s);
			if (st.error) loadError = `review: ${st.error}`;
			extensions = [
				...reviewExtensions({
					onCommand: (name, itemId, args) => handleCommand(name, itemId, args),
					onStale: (ids) => s.markStale(ids),
					onHistory: handleHistory,
					density,
					getItem: (itemId) => get(s).items.find((i) => i.id === itemId)
				})
			];
			store = s;
			text = data.report.report_content ?? '';
			let lastItems: ReviewItem[] | null = null;
			unsubscribe = s.subscribe((v) => {
				if (v.items === lastItems) return;
				lastItems = v.items;
				scheduleSync();
			});
		} catch (e) {
			if (reportId === id) loadError = e instanceof Error ? e.message : String(e);
		}
	}

	const view = () => editorRef?.getView() ?? null;

	/** Put the store's items into the editor field once the editor (and its extensions) has mounted. */
	function scheduleSync(): void {
		if (syncQueued) return;
		syncQueued = true;
		void tick().then(() => {
			syncQueued = false;
			const v = view();
			if (!v || !store) return;
			v.dispatch(syncItems(v.state, get(store).items, { textHash: null }));
		});
	}

	/** Item events: posted through the store with "Post events" on, else recorded on the local item only. */
	function recordEvents(events: ItemEvent[], statuses: Record<string, ItemStatus>): void {
		const s = store;
		const v = view();
		if (!s || !events.length) return;
		const doc = v?.state.doc.toString() ?? '';
		postChain = postChain.then(async () => {
			const h = await textHash(doc);
			for (const ev of events) {
				const cur = get(s).items.find((i) => i.id === ev.itemId);
				const status = statuses[ev.itemId] ?? cur?.status ?? 'open';
				if (postEvents && cur?.lane !== 'chat') {
					void s.setStatus(ev.itemId, status, { command: ev.command, textHash: h, detail: ev.detail });
				} else if (cur) {
					const entry = { event: ev.command, actor: 'user', text_hash: h, detail: ev.detail ?? {} };
					s.upsert([{ ...cur, status, history: [...cur.history, entry] }]);
				}
			}
		});
	}

	function handleCommand(name: CommandName, itemId?: string, args?: Record<string, unknown>): void {
		const s = store;
		const v = view();
		if (!s || !v) return;
		if (name === 'rerun') {
			if (postEvents) void s.rerun(v.state.doc.toString());
			else console.info('[dev/review-rail] rerun skipped: post events is off');
			return;
		}
		if (name === 'finalise') return;
		const items = get(s).items;
		const item = itemId ? (items.find((i) => i.id === itemId) ?? null) : null;
		const result = runCommand(name, {
			doc: v.state.doc.toString(),
			items,
			item,
			args,
			sections: null,
			widgetPos: widgetPosOf(v.state),
			textHash: null
		});
		if (result.error) {
			console.warn(`[dev/review-rail] ${name} ${itemId ?? ''}: ${result.error}`);
			return;
		}
		if (result.focus) {
			v.dispatch({ selection: { anchor: result.focus.from }, effects: EditorView.scrollIntoView(result.focus.from, { y: 'center' }) });
		}
		if (result.changes || (result.statuses && Object.keys(result.statuses).length)) {
			v.dispatch(commandTransaction(v.state, result, items, { sections: null, textHash: null }));
		}
		recordEvents([...(result.event ? [result.event] : []), ...(result.events ?? [])], result.statuses ?? {});
	}

	function handleHistory(ev: ReviewHistoryEvent): void {
		const command = ev.kind === 'undo' ? 'undo' : ev.command;
		if (!USER_COMMANDS.has(command)) return;
		recordEvents(
			[{ itemId: ev.itemId, command: command as UserCommand, detail: { via: ev.kind === 'undo' ? 'cmd_z' : 'redo' } }],
			{ [ev.itemId]: ev.status }
		);
	}

	function handleDensity(d: Density): void {
		density = d;
		view()?.dispatch({ effects: setDensity.of(d) });
	}

	const fmt = (o: Record<string, unknown> | undefined) =>
		o && Object.keys(o).length
			? Object.entries(o)
					.map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
					.join(' · ')
			: '—';

	onMount(() => void loadReports());
	onDestroy(teardown);
</script>

<svelte:head><title>Review rail (dev)</title></svelte:head>

<div class="flex min-h-screen flex-col gap-4 bg-gray-950 p-4 text-gray-100">
	<header class="flex flex-wrap items-center gap-3">
		<h1 class="text-lg font-semibold">Review rail (dev)</h1>
		<form
			class="flex items-center gap-2"
			onsubmit={(e) => {
				e.preventDefault();
				void openReport(pasted);
			}}
		>
			<label for="rr-dev-id" class="text-sm text-gray-400">Report id</label>
			<input
				id="rr-dev-id"
				class="w-80 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm"
				bind:value={pasted}
				placeholder="paste a report id"
			/>
			<button type="submit" class="rounded bg-gray-800 px-3 py-1 text-sm hover:bg-gray-700">Load</button>
		</form>
		<label class="ml-auto flex items-center gap-2 text-sm">
			<input type="checkbox" bind:checked={postEvents} />
			Post events
		</label>
		<span class="text-xs text-gray-500">{postEvents ? 'events and re-review reach the server' : 'local only: nothing is posted'}</span>
	</header>

	<div class="flex min-h-0 flex-1 gap-4">
		<nav class="w-64 shrink-0 overflow-y-auto" aria-label="Recent reports">
			<h2 class="mb-2 text-xs uppercase tracking-wide text-gray-500">Recent reports</h2>
			{#if listLoading}<p class="text-sm text-gray-500">Loading…</p>{/if}
			{#if listError}<p class="text-sm text-red-400">{listError}</p>{/if}
			<ul class="flex flex-col gap-1">
				{#each reports as r (r.id)}
					<li>
						<button
							class="w-full rounded px-2 py-1 text-left text-sm hover:bg-gray-800 {reportId === r.id ? 'bg-gray-800' : ''}"
							onclick={() => void openReport(r.id)}
						>
							<span class="block truncate">{r.description || r.report_type || r.id}</span>
							<span class="flex items-center gap-2 text-xs text-gray-500">
								{r.created_at?.slice(0, 16).replace('T', ' ') ?? ''}
								<span data-testid="run-badge-{r.id}" class={runs[r.id] ? 'text-emerald-400' : 'text-gray-600'}>
									{r.id in runs ? (runs[r.id] ?? 'no run') : '…'}
								</span>
							</span>
						</button>
					</li>
				{/each}
			</ul>
		</nav>

		<main class="flex min-w-0 flex-1 flex-col gap-3">
			{#if loadError}<p class="text-sm text-red-400">{loadError}</p>{/if}
			{#if run}
				<dl data-testid="run-meta" class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded border border-gray-800 p-2 text-xs">
					<dt class="text-gray-500">run</dt><dd>{run.id} · {run.pathway}</dd>
					<dt class="text-gray-500">mode</dt><dd>{run.mode}</dd>
					<dt class="text-gray-500">engine_version</dt><dd>{run.engine_version}</dd>
					<dt class="text-gray-500">lanes</dt><dd>{fmt(run.lanes)}</dd>
					<dt class="text-gray-500">timings_ms</dt><dd>{fmt(run.timings_ms)}</dd>
					<dt class="text-gray-500">errors</dt><dd class={Object.keys(run.errors ?? {}).length ? 'text-red-400' : ''}>{fmt(run.errors)}</dd>
				</dl>
			{:else if store}
				<p class="text-sm text-gray-500">This report has no review run.</p>
			{/if}
			{#if store && text !== null}
				<div class="flex min-h-0 flex-1 gap-3">
					<div class="min-w-0 flex-1 rounded border border-gray-800 p-2">
						{#key reportId}
							<ReportEditor bind:this={editorRef} content={text} extraExtensions={extensions} />
						{/key}
					</div>
					<div class="shrink-0 overflow-y-auto">
						<ReviewRail {store} onCommand={handleCommand} bind:density onDensity={handleDensity} force={true} devControls />
					</div>
				</div>
			{/if}
		</main>
	</div>
</div>
