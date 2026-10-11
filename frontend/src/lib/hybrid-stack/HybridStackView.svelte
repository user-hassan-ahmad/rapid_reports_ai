<script lang="ts">
	// Scratchpad v2 (spec 2026-10-11 §2): live strip, abnormal regions with their check chips, the
	// assumed-normal tray, the conclusion and the gate. Every line is the radiologist's own sentence from the
	// verbatim text; a click opens it for editing (typing, or dictation at the caret / over the selection).
	import { crossfade, fade, slide } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { buildView } from './stackState';
	import { CONCLUSION, GENERAL, OTHER, TECHNIQUE, regionStates, showsGroup } from './regionState';
	import type { VisibleChip } from './chips';
	import type { StackUnit, ViewRow } from './types';

	export type ConclusionState =
		| { kind: 'dictated' }
		| { kind: 'none'; failed?: boolean }
		| { kind: 'loading' }
		| { kind: 'draft'; text: string; stale: boolean; edited: boolean; typed?: boolean };

	let {
		units,
		groups,
		pillRegions,
		pending = [],
		ghost = '',
		chips = [],
		conclusion = { kind: 'none' },
		gateConfirmed = false,
		deleteRegion = null,
		incoming = null,
		onMove,
		onEditLine,
		onEditing = () => {},
		onChipAccept,
		onChipRemove = () => {},
		onDraftEdit = () => {},
		onDraftRefresh = () => {},
		onConfirm,
		onDeleteRegion = () => {},
		onAppend = () => {}
	}: {
		units: StackUnit[];
		groups: string[];
		/** The schema's regions except the catch-all: the tray. */
		pillRegions: string[];
		pending?: string[];
		ghost?: string;
		chips?: VisibleChip[];
		conclusion?: ConclusionState;
		gateConfirmed?: boolean;
		/** A voice "delete the X line": the region whose lines wait for a Delete click (null: none). */
		deleteRegion?: string | null;
		/** Dictation for the field open for editing: inserted at its caret / over its selection. */
		incoming?: { seq: number; text: string } | null;
		onMove: (id: number, group: string) => void;
		onEditLine: (unitId: number, part: number | null, text: string) => void;
		/** Whether a line or the draft is open for editing (dictation then goes there). */
		onEditing?: (active: boolean) => void;
		/** An optional chip opted in (click +). */
		onChipAccept: (text: string) => void;
		/** An included chip removed (click ×): never stated. */
		onChipRemove?: (text: string) => void;
		onDraftEdit?: (text: string) => void;
		onDraftRefresh?: () => void;
		onConfirm: () => void;
		onDeleteRegion?: (region: string, confirmed: boolean) => void;
		/** A finding typed into the new-line field (Enter): appended to the dictation as said. */
		onAppend?: (text: string) => void;
	} = $props();

	const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	const ms = reduced ? 0 : 280;
	const [send, receive] = crossfade({ duration: ms, fallback: (node) => fade(node, { duration: ms }) });

	const view = $derived(buildView(units, groups));
	const states = $derived(regionStates(units, pillRegions));
	const shown = $derived(
		view.groups.filter(
			(g) =>
				states.abnormal.includes(g.name) ||
				(g.name === GENERAL && showsGroup(units, GENERAL)) ||
				(g.name === OTHER && showsGroup(units, OTHER))
		)
	);
	const technique = $derived(view.groups.find((g) => g.name === TECHNIQUE));
	const conclusionRows = $derived(view.groups.find((g) => g.name === CONCLUSION)?.rows ?? []);
	const dictatedNormalWords = $derived(new Map(states.dictatedNormal.map((d) => [d.region, d.words])));
	const trayRegions = $derived(pillRegions.filter((r) => !states.abnormal.includes(r)));
	// The gate never unlocks an impression nobody has seen (spec §5): a conclusion must exist (dictated,
	// drafted or typed). A failed draft never blocks: the radiologist types one or asks again.
	const hasConclusion = $derived(conclusionRows.length > 0 || (conclusion.kind === 'draft' && conclusion.text.trim().length > 0));
	const includedList = $derived(chips.filter((c) => c.state === 'included').map((c) => c.text));
	const assumedList = $derived([...states.assumedNormal, ...states.remainder.map((r) => `remainder of ${r.toLowerCase()}`)]);

	// ── editing: one field at a time (a line, or the draft) ─────────────────────────────────────────
	let editing: { unitId: number; part: number | null } | null = $state(null);
	let editValue = $state('');
	let field: HTMLInputElement | null = $state(null);
	let draftField: HTMLTextAreaElement | null = $state(null);
	let draftFocused = $state(false);
	let newLine = $state('');
	let newField: HTMLInputElement | null = $state(null);
	let newFocused = $state(false);
	function appendNew() {
		const t = newLine.trim();
		if (t) onAppend(t);
		newLine = '';
	}
	let lastSeq = -1;

	function partIndex(r: ViewRow): number | null {
		if (r.partOf === null) return null;
		const u = units.find((x) => x.id === r.unitId);
		const k = u?.parts?.findIndex((p) => p.text === r.text) ?? -1;
		return k >= 0 ? k : null;
	}
	function rowText(unitId: number, part: number | null): string {
		const u = units.find((x) => x.id === unitId);
		if (!u) return '';
		return part === null ? u.text : (u.parts?.[part]?.text ?? '');
	}
	function open(r: ViewRow) {
		commit();
		editing = { unitId: r.unitId, part: partIndex(r) };
		editValue = r.text;
		onEditing(true);
	}
	function commit() {
		if (!editing) return;
		const e = editing;
		editing = null;
		onEditing(draftFocused || newFocused);
		if (editValue.trim() !== rowText(e.unitId, e.part).trim()) onEditLine(e.unitId, e.part, editValue.trim());
	}
	const isEditing = (r: ViewRow) => editing !== null && editing.unitId === r.unitId && editing.part === partIndex(r);

	/** Dictated words into a field: over the selection, or at the caret, with spaces at the joins. */
	function insertInto(el: HTMLInputElement | HTMLTextAreaElement, value: string, text: string): { value: string; caret: number } {
		const from = el.selectionStart ?? value.length;
		const to = el.selectionEnd ?? from;
		const before = value.slice(0, from);
		const after = value.slice(to);
		const lead = before && !/\s$/.test(before) ? ' ' : '';
		const trail = after && !/^[\s.,;:?!]/.test(after) ? ' ' : '';
		return { value: before + lead + text.trim() + trail + after, caret: (before + lead + text.trim()).length };
	}
	$effect(() => {
		if (!incoming || incoming.seq === lastSeq) return;
		lastSeq = incoming.seq;
		const el = editing ? field : draftFocused ? draftField : newFocused ? newField : null;
		if (!el) return;
		const cur = editing ? editValue : newFocused ? newLine : conclusion.kind === 'draft' ? conclusion.text : '';
		const r = insertInto(el, cur, incoming.text);
		if (editing) editValue = r.value;
		else if (newFocused) newLine = r.value;
		else onDraftEdit(r.value);
		queueMicrotask(() => el.setSelectionRange(r.caret, r.caret));
	});
	function focusOnMount(el: HTMLInputElement) {
		el.focus();
	}

	let dragOver: string | null = $state(null);
	function drop(e: DragEvent, group: string) {
		e.preventDefault();
		dragOver = null;
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (Number.isFinite(id)) onMove(id, group);
	}
</script>

{#snippet line(r: ViewRow, nested: boolean)}
	<li class="group/line flex items-start gap-1" in:receive={{ key: r.text }} out:send={{ key: r.text }}>
		<span
			class="mt-1 cursor-grab select-none text-[10px] text-gray-600 opacity-0 group-hover/line:opacity-100"
			draggable="true"
			role="button"
			tabindex="-1"
			aria-label="Move line"
			ondragstart={(e) => e.dataTransfer?.setData('text/plain', String(r.unitId))}>⋮⋮</span>
		<div class="min-w-0 flex-1 {nested ? 'pl-4' : ''}">
			{#if isEditing(r)}
				<input
					bind:this={field}
					bind:value={editValue}
					use:focusOnMount
					class="w-full rounded bg-white/[0.06] px-1 text-sm leading-6 text-gray-100 outline outline-1 outline-emerald-500/50"
					aria-label="Edit line"
					onblur={commit}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === 'Escape') {
							e.preventDefault();
							commit();
						}
					}}
				/>
				<span class="text-[10px] text-emerald-400">Listening to edit · Enter to finish</span>
			{:else}
				<button type="button" class="w-full rounded px-1 text-left text-sm leading-6 text-gray-200 hover:bg-white/[0.05]" onclick={() => open(r)}>
					{#if nested}<span aria-hidden="true" class="text-gray-500">↳ </span>{/if}{r.text}
					{#if r.structure}<span class="ml-1 text-xs text-gray-500">· {r.structure}</span>{/if}
					{#if r.pinned}<span class="ml-1 text-xs text-gray-500" title="Placed by you">•</span>{/if}
				</button>
			{/if}
			{#if r.children.length}
				<ul>{#each r.children as c (c.unitId + ':' + c.text)}{@render line(c, true)}{/each}</ul>
			{/if}
		</div>
	</li>
{/snippet}

<div class="space-y-3" data-testid="hybrid-stack">
	<!-- Live strip: the words being spoken and sentences not placed yet -->
	{#if view.unplaced.length || pending.length || ghost}
		<section aria-label="Just dictated" class="rounded border border-white/5 bg-white/[0.02] px-2 py-1">
			<ul>
				{#each view.unplaced as r (r.text)}<li class="text-sm leading-6 text-gray-300" out:send={{ key: r.text }}>{r.text}</li>{/each}
				{#each pending as text (text)}<li class="text-sm leading-6 text-gray-300" out:send={{ key: text }}>{text}</li>{/each}
				{#if ghost}<li class="text-sm italic leading-6 text-gray-400">{ghost}</li>{/if}
			</ul>
		</section>
	{/if}

	<input
		bind:this={newField}
		bind:value={newLine}
		class="w-full rounded border border-white/5 bg-transparent px-2 py-1 text-sm text-gray-200 placeholder:text-gray-600 focus:border-emerald-500/40 focus:outline-none"
		placeholder="Type a finding… (Enter adds it)"
		aria-label="New line"
		onfocus={() => {
			newFocused = true;
			onEditing(true);
		}}
		onblur={() => {
			newFocused = false;
			onEditing(editing !== null || draftFocused);
		}}
		onkeydown={(e) => {
			if (e.key === 'Enter') {
				e.preventDefault();
				appendNew();
			}
		}}
	/>

	{#if technique}
		<section aria-label={TECHNIQUE} class="text-gray-400">
			<ul>{#each technique.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		</section>
	{/if}

	<!-- Scratchpad: abnormal regions only -->
	{#each shown as g (g.name)}
		{@const mine = chips.filter((c) => c.region === g.name)}
		<section
			animate:flip={{ duration: ms }}
			transition:slide={{ duration: ms }}
			class="rounded {dragOver === g.name ? 'bg-emerald-500/10' : ''} {deleteRegion === g.name ? 'outline outline-1 outline-rose-500/60' : ''}"
			ondragover={(e) => {
				e.preventDefault();
				dragOver = g.name;
			}}
			ondragleave={() => (dragOver = null)}
			ondrop={(e) => drop(e, g.name)}
			aria-label={g.name}
		>
			<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">{g.name}</h3>
			<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
			{#if states.remainder.includes(g.name)}
				<p class="px-1 text-xs italic text-gray-500">Remainder of {g.name.toLowerCase()}: assumed normal</p>
			{/if}
			{#if deleteRegion === g.name}
				<div class="mt-1 flex gap-2 px-1 text-xs">
					<button type="button" class="rounded bg-rose-500/20 px-2 py-0.5 text-rose-200" onclick={() => onDeleteRegion(g.name, true)}>Delete these lines</button>
					<button type="button" class="rounded px-2 py-0.5 text-gray-400 hover:text-gray-200" onclick={() => onDeleteRegion(g.name, false)}>Keep</button>
				</div>
			{/if}
			{#if mine.length}
				<ul class="mt-0.5 px-1" aria-label="Suggestions for {g.name}">
					{#each mine.filter((c) => c.state === 'included') as c (c.text)}
						<li class="flex items-center gap-1 text-sm italic leading-6 text-gray-400" transition:fade={{ duration: ms }} data-chip="included">
							<span>{c.text}</span>
							<button type="button" class="rounded px-1 text-xs not-italic text-gray-500 hover:text-rose-300" title="Remove: not stated in the report"
								aria-label="Remove {c.text}" onclick={() => onChipRemove(c.text)}>×</button>
						</li>
					{/each}
				</ul>
				<div class="mt-1 flex flex-wrap gap-1.5 px-1">
					{#each mine.filter((c) => c.state === 'optional') as c (c.text)}
						<button
							type="button"
							transition:fade={{ duration: ms }}
							data-chip="optional"
							class="rounded-full border border-dashed border-white/20 px-2 py-0.5 text-xs text-gray-400 hover:border-emerald-400/50 hover:text-emerald-200"
							title="Add to the report"
							onclick={() => onChipAccept(c.text)}>+ {c.text}</button>
					{/each}
				</div>
			{/if}
		</section>
	{/each}

	<!-- Assumed-normal tray -->
	{#if trayRegions.length}
		<section aria-label="Normal regions" class="border-t border-white/5 pt-2">
			<div class="flex flex-wrap gap-1.5">
				{#each trayRegions as r (r)}
					{@const words = dictatedNormalWords.get(r)}
					<!-- No transition on pills: a fade-out with flip left removed pills in the DOM (hand read 2026-10-11);
					     the region sliding into the scratchpad carries the motion. -->
					<span
						class="rounded-full px-2 py-0.5 text-xs {words
							? 'border border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
							: 'border border-dashed border-white/20 text-gray-400'}"
						title={words ? `Dictated: ${words.join(' ')}` : 'Assumed normal (not dictated)'}
						data-state={words ? 'dictated' : 'assumed'}>{r}</span>
				{/each}
			</div>
		</section>
	{/if}

	<!-- Conclusion -->
	<section aria-label={CONCLUSION} class="border-t border-white/5 pt-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">{CONCLUSION}</h3>
		{#if conclusionRows.length}
			<ul>{#each conclusionRows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		{:else if conclusion.kind === 'draft' || conclusion.kind === 'none'}
			{#if conclusion.kind === 'draft'}
				<p class="text-[10px] uppercase tracking-wide {conclusion.typed ? 'text-gray-500' : 'text-amber-300/80'}">{conclusion.typed ? 'Typed' : `AI draft${conclusion.edited ? ' · edited' : ''}`}</p>
			{:else if conclusion.failed}
				<p class="text-[10px] text-amber-300/80">The draft could not be made: type or dictate one, or try again.</p>
			{/if}
			<textarea
				bind:this={draftField}
				class="mt-0.5 w-full resize-y rounded bg-white/[0.04] px-1 text-sm leading-6 text-gray-100"
				rows="3"
				aria-label="Conclusion draft"
				value={conclusion.kind === 'draft' ? conclusion.text : ''}
				placeholder="Type or dictate a conclusion"
				oninput={(e) => onDraftEdit((e.target as HTMLTextAreaElement).value)}
				onfocus={() => {
					draftFocused = true;
					onEditing(true);
				}}
				onblur={() => {
					draftFocused = false;
					onEditing(editing !== null || newFocused);
				}}
			></textarea>
			{#if conclusion.kind === 'draft' && conclusion.stale && !conclusion.typed}
				<button type="button" class="text-xs text-amber-300 hover:text-amber-200" onclick={onDraftRefresh}>Findings changed — refresh?</button>
			{:else if conclusion.kind === 'none'}
				<button type="button" class="text-xs text-gray-400 hover:text-gray-200" onclick={onDraftRefresh}>Draft one</button>
			{/if}
		{:else}
			<p class="px-1 text-sm italic text-gray-500">Drafting a conclusion…</p>
		{/if}
	</section>

	<!-- Gate: one click confirms the conclusion and the normals nobody dictated -->
	<section aria-label="Confirm" class="rounded border border-white/10 bg-white/[0.02] p-2 text-xs text-gray-300">
		<p class="mb-1 text-gray-400">Before generating, confirm:</p>
		<ul class="list-disc space-y-0.5 pl-4">
			<li>the conclusion above{#if !hasConclusion}<span class="text-amber-300/80"> (none yet)</span>{/if}</li>
			{#if includedList.length}<li>stated, not dictated: {includedList.join(' ')}</li>{/if}
			<li>normal, not dictated: {#if assumedList.length}{assumedList.join(', ')}{:else}<span class="text-gray-500">none</span>{/if}</li>
			{#if states.dictatedNormal.length}
				<li>
					<details>
						<summary class="cursor-pointer">normal as dictated: {states.dictatedNormal.map((d) => d.region).join(', ')}</summary>
						<ul class="mt-1 space-y-0.5 text-gray-400">
							{#each states.dictatedNormal as d (d.region)}<li>{d.region}: “{d.words.join(' ')}”</li>{/each}
						</ul>
					</details>
				</li>
			{/if}
		</ul>
		<button
			type="button"
			class="mt-2 rounded px-3 py-1 text-xs font-medium {gateConfirmed ? 'bg-emerald-500/20 text-emerald-200' : 'bg-white/10 text-gray-100 hover:bg-white/15'}"
			disabled={gateConfirmed || !hasConclusion}
			onclick={onConfirm}>{gateConfirmed ? 'Confirmed ✓' : 'Confirm'}</button>
	</section>
</div>
