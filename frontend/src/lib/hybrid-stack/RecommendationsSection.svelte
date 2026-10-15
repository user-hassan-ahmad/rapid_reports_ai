<script lang="ts">
	/**
	 * Recommendations (spec 2026-10-14 §7.1, §7.4): one line per applied guideline card, below the Conclusion. A line
	 * is edited or deleted like any scratchpad line (deleting undoes the Apply). Amber when a value behind it changed
	 * or its finding went: the radiologist re-applies or deletes it; nothing changes it on its own. Hidden while empty.
	 */
	import type { AppliedRec } from './types';

	let { lines, onEdit, onDelete }: { lines: AppliedRec[]; onEdit: (key: string, text: string) => void; onDelete: (key: string) => void } = $props();
	let editing = $state<string | null>(null);
	let draft = $state('');
	const why = (r: AppliedRec) => (r.stale === 'values' ? 'values changed' : r.stale === 'finding' ? 'finding removed' : '');
	function save(key: string) {
		if (editing !== key) return;
		if (draft.trim()) onEdit(key, draft.trim());
		editing = null;
	}
</script>

{#if lines.length}
	<section aria-label="Recommendations" class="border-t border-white/5 pt-2" data-testid="recommendations">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">Recommendations</h3>
		<ul class="mt-0.5 flex flex-col gap-1">
			{#each lines as r, i (r.key)}
				<li class="rounded px-1 text-sm leading-6 {r.stale ? 'border-l-2 border-amber-400/60 bg-amber-500/[0.06] text-amber-100' : 'text-gray-100'}">
					{#if editing === r.key}
						<input class="w-full rounded border border-white/10 bg-white/[0.04] px-1 text-sm text-gray-100" aria-label={`Recommendation ${i + 1}`} bind:value={draft}
							onkeydown={(e) => { if (e.key === 'Enter') save(r.key); else if (e.key === 'Escape') editing = null; }} onblur={() => save(r.key)} />
					{:else}
						<span>{r.text}</span>
						{#if why(r)}<span class="ml-1 text-[10px] uppercase tracking-wide text-amber-300/80">{why(r)}</span>{/if}
						{#if r.chosen_from}<span class="ml-1 text-[10px] text-gray-500">chosen by you from {r.chosen_from}</span>{/if}
						<span class="ml-1 inline-flex gap-2 text-xs">
							<button type="button" class="text-gray-400 hover:text-gray-200" aria-label={`Edit recommendation ${i + 1}`} onclick={() => { draft = r.text; editing = r.key; }}>Edit</button>
							<button type="button" class="text-gray-400 hover:text-red-300" aria-label={`Delete recommendation ${i + 1}`} onclick={() => onDelete(r.key)}>Delete</button>
						</span>
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/if}
