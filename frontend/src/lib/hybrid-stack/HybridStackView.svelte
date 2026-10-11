<script lang="ts">
	// The grouped view of the verbatim dictation (spec §3.1). Read-only text: a click selects the
	// sentence in the verbatim editor; a drag to another group pins it there.
	import { buildView } from './stackState';
	import type { StackUnit, ViewRow } from './types';

	let {
		units,
		groups,
		pending = [],
		ghost = '',
		onSelect,
		onMove
	}: {
		units: StackUnit[];
		groups: string[];
		/** Sentences written but not yet held by a unit (shown at once, faded). */
		pending?: string[];
		/** Words being spoken, not yet final. */
		ghost?: string;
		onSelect: (id: number) => void;
		onMove: (id: number, group: string) => void;
	} = $props();

	const view = $derived(buildView(units, groups));
	let dragOver: string | null = $state(null);

	function drop(e: DragEvent, group: string) {
		e.preventDefault();
		dragOver = null;
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (Number.isFinite(id)) onMove(id, group);
	}
</script>

{#snippet line(r: ViewRow, nested: boolean)}
	<li>
		<button
			type="button"
			draggable="true"
			class="w-full text-left text-sm leading-6 hover:bg-slate-50 rounded px-1 {nested ? 'pl-5 text-slate-600' : ''}"
			ondragstart={(e) => e.dataTransfer?.setData('text/plain', String(r.unitId))}
			onclick={() => onSelect(r.unitId)}
		>
			{#if nested}<span aria-hidden="true" class="text-slate-400">↳ </span>{/if}{r.text}
			{#if r.structure}<span class="ml-1 text-xs text-slate-400">· {r.structure}</span>{/if}
			{#if r.pinned}<span class="ml-1 text-xs text-slate-400" title="Placed by you">•</span>{/if}
		</button>
		{#if r.children.length}
			<ul>{#each r.children as c (c.unitId + ':' + c.text)}{@render line(c, true)}{/each}</ul>
		{/if}
	</li>
{/snippet}

<div class="space-y-3" data-testid="hybrid-stack">
	{#each view.groups as g (g.name)}
		<section
			class="rounded {dragOver === g.name ? 'bg-sky-50' : ''}"
			ondragover={(e) => { e.preventDefault(); dragOver = g.name; }}
			ondragleave={() => (dragOver = null)}
			ondrop={(e) => drop(e, g.name)}
			aria-label={g.name}
		>
			<h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">{g.name}</h3>
			<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		</section>
	{/each}
	{#if view.unplaced.length || pending.length || ghost}
		<section class="opacity-50" aria-label="Just dictated">
			<h3 class="text-xs font-semibold uppercase tracking-wide text-slate-400">Just dictated</h3>
			<ul>
				{#each view.unplaced as r (r.unitId)}{@render line(r, false)}{/each}
				{#each pending as text, k (k + ':' + text)}<li class="text-sm leading-6 px-1">{text}</li>{/each}
				{#if ghost}<li class="text-sm leading-6 px-1 italic">{ghost}</li>{/if}
			</ul>
		</section>
	{/if}
</div>
