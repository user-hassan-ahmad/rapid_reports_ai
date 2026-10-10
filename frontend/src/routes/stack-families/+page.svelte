<script lang="ts">
	// Review of reconciled stack families (spec §3.3). Not a dev route: production review; the server
	// allows only RR_STACK_REVIEWERS and returns 403 to anyone else.
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config.js';
	import { token } from '$lib/stores/auth';

	type Fam = { key: string; scan_type: string; regions: { name: string; includes: string }[]; source: string; status: string };
	let rows: Fam[] = $state([]);
	let error = $state('');
	let edits: Record<string, string> = $state({});
	const headers = (): Record<string, string> => ({
		'Content-Type': 'application/json',
		...($token ? { Authorization: `Bearer ${$token}` } : {})
	});

	async function load() {
		const res = await fetch(`${API_URL}/api/canvas/stack/families?status=provisional`, { headers: headers() });
		if (!res.ok) {
			error = res.status === 403 ? 'Not a reviewer.' : `Error ${res.status}`;
			return;
		}
		rows = await res.json();
		edits = Object.fromEntries(rows.map((r) => [r.key, JSON.stringify(r.regions, null, 1)]));
	}
	async function decide(key: string, status: 'approved' | 'rejected') {
		const body: Record<string, unknown> = { status };
		if (status === 'approved') {
			try {
				body.regions = JSON.parse(edits[key]);
			} catch {
				error = `The regions for ${key} are not valid JSON.`;
				return;
			}
		}
		const res = await fetch(`${API_URL}/api/canvas/stack/families/${encodeURIComponent(key)}`, {
			method: 'POST',
			headers: headers(),
			body: JSON.stringify(body)
		});
		if (res.ok) rows = rows.filter((r) => r.key !== key);
		else error = `Could not update ${key} (${res.status}).`;
	}
	onMount(load);
</script>

<div class="mx-auto max-w-4xl p-6 space-y-4">
	<h1 class="text-lg font-semibold">Stack families awaiting review</h1>
	{#if error}<p class="text-sm text-red-600">{error}</p>{/if}
	{#each rows as r (r.key)}
		<section class="rounded border p-3 space-y-2">
			<h2 class="font-medium">{r.scan_type} <span class="text-xs text-slate-500">({r.source})</span></h2>
			<textarea class="w-full h-48 font-mono text-xs border rounded p-2" bind:value={edits[r.key]}></textarea>
			<div class="flex gap-2">
				<button type="button" class="rounded bg-emerald-700 px-3 py-1 text-white text-sm" onclick={() => decide(r.key, 'approved')}>Approve (with edits)</button>
				<button type="button" class="rounded bg-slate-200 px-3 py-1 text-sm" onclick={() => decide(r.key, 'rejected')}>Reject</button>
			</div>
		</section>
	{:else}
		{#if !error}<p class="text-sm text-slate-500">Nothing to review.</p>{/if}
	{/each}
</div>
