<script lang="ts">
	// Scratchpad checklist (spec 2026-10-11-scratchpad-checklist §3): live strip, the referral row, abnormal
	// regions with their amber rows and the normals that will be reported, the tray, the conclusion and the gate
	// bar. Every line is the radiologist's own sentence from the verbatim text; a click opens it for editing.
	// Rows are asked, never assumed: a tap adds only the sentences listed above its button.
	import { crossfade, fade, slide } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { buildView } from './stackState';
	import { CONCLUSION, GENERAL, OTHER, TECHNIQUE, regionStates, showsGroup } from './regionState';
	import { answerLabel, openCount, quietLine, rowSentences, unansweredChecks } from './items';
	import type { StackItem, StackUnit, ViewRow } from './types';

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
		items = [],
		tapped = [],
		removed = [],
		assumed = {},
		namedNormals = false,
		skipped = [],
		reviewing = false,
		reviewWaiting = false,
		reviewFailed = false,
		conclusion = { kind: 'none' },
		gateConfirmed = false,
		deleteRegion = null,
		incoming = null,
		onMove,
		onEditLine,
		onEditing = () => {},
		onAnswer = () => {},
		onRemoveSentence = () => {},
		onDictateInto = () => {},
		onSkip = () => {},
		onDraftEdit = () => {},
		onDraftRefresh = () => {},
		onConfirm,
		onDeleteRegion = () => {},
		onAppend = () => {},
		syncing = false
	}: {
		units: StackUnit[];
		groups: string[];
		/** The schema's regions except the catch-all: the tray. */
		pillRegions: string[];
		pending?: string[];
		ghost?: string;
		/** Checklist rows: referral and finding (answered ones fold away; the parent drops them). */
		items?: StackItem[];
		/** Rows the radiologist answered with a tap: their listed sentences are stated. */
		tapped?: string[];
		/** Sentences the radiologist removed (×): never stated. */
		removed?: string[];
		/** Region normals that will be reported unless removed (the slim sheet, checked against the dictation). */
		assumed?: Record<string, string[]>;
		/** No sheet this session: untouched regions are confirmed by name (v2). With a sheet, only sentences are. */
		namedNormals?: boolean;
		/** Rows skipped (finding checks) or marked not assessed (referral rows): folded, nothing stated. */
		skipped?: string[];
		/** The end-of-dictation review is running / will run when dictation stops. */
		reviewing?: boolean;
		reviewWaiting?: boolean;
		/** The review failed: no finding checks this time, and the radiologist is told. */
		reviewFailed?: boolean;
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
		/** A row answered with a tap: its listed sentences are added as the radiologist's answer. */
		onAnswer?: (id: string) => void;
		/** A row sentence or an assumed normal removed (×): never stated. */
		onRemoveSentence?: (sentence: string) => void;
		/** "Dictate" on a row: the next words go under that region. */
		onDictateInto?: (region: string) => void;
		/** Skip a finding check, or mark a referral question not assessed: folded, nothing stated. */
		onSkip?: (id: string) => void;
		onDraftEdit?: (text: string) => void;
		onDraftRefresh?: () => void;
		onConfirm: () => void;
		onDeleteRegion?: (region: string, confirmed: boolean) => void;
		/** A finding typed into the new-line field (Enter): appended to the dictation as said. */
		onAppend?: (text: string) => void;
		/** The grouping has not caught up with the text yet: Confirm waits (the block must match what is shown). */
		syncing?: boolean;
	} = $props();

	const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	const ms = reduced ? 0 : 280;
	const [send, receive] = crossfade({ duration: ms, fallback: (node) => fade(node, { duration: ms }) });

	const view = $derived(buildView(units, groups));
	const states = $derived(regionStates(units, pillRegions));
	const shown = $derived(
		view.groups.filter(
			(g) =>
				g.members.some((m) => states.abnormal.includes(m)) ||
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
	const referrals = $derived(items.filter((i) => i.kind === 'referral'));
	const shownNames = $derived(new Set(shown.map((g) => g.name)));
	const covered = $derived(new Set(shown.flatMap((g) => g.members)));
	const rowsFor = (region: string) => items.filter((i) => i.kind === 'finding' && i.region === region);
	// A joined card holds the rows and normals of the regions it spans, unless a region has its own card.
	const ownMembers = (g: { name: string; members: string[] }) => g.members.filter((m) => m === g.name || !shownNames.has(m));
	// A finding row whose region has no card (the writer named a region outside the scratchpad) shows up top.
	const looseRows = $derived(items.filter((i) => i.kind === 'finding' && !covered.has(i.region)));
	const openRows = $derived(openCount(items, tapped, removed, skipped));
	const unanswered = $derived(unansweredChecks(items, tapped, removed, skipped));
	const keptAssumed = (region: string) => {
		const gone = new Set(removed.map((r) => r.trim().toLowerCase().replace(/\.$/, '')));
		return (assumed[region] ?? []).filter((s) => !gone.has(s.trim().toLowerCase().replace(/\.$/, '')));
	};
	// Every statement that will be reported without being dictated: region normals, and regions confirmed by
	// name where no sentences exist yet.
	const assumedCount = $derived(
		trayRegions.filter((r) => !dictatedNormalWords.has(r)).reduce((n, r) => n + (namedNormals ? 1 : keptAssumed(r).length), 0) +
			states.abnormal.reduce((n, r) => n + keptAssumed(r).length, 0)
	);
	let expanded: string[] = $state([]);
	let openPill: string | null = $state(null);

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

{#snippet row(it: StackItem, label: string | null)}
	<!-- One compact line (hand read 2026-10-12): tag, question, its sentences inline with ×, then the answer. The
	     reason sits behind ⓘ. A tap adds exactly the sentences shown. -->
	{@const listed = rowSentences(it, removed)}
	{#if skipped.includes(it.id)}
		<!-- skipped or not assessed: folded, nothing stated -->
	{:else if tapped.includes(it.id)}
		<div class="flex flex-wrap items-baseline gap-x-2 rounded-md border-l-2 border-emerald-500/60 bg-emerald-500/[0.06] px-2 py-1 text-sm" data-row="tapped">
			{#if label}<span class="text-[10px] uppercase tracking-wide text-emerald-300/70">{label}</span>{/if}
			<span class="text-emerald-200">✓ {listed.join(' ')}</span>
		</div>
	{:else if it.answered}
		<div class="flex flex-wrap items-baseline gap-x-2 rounded-md border-l-2 border-emerald-500/60 bg-emerald-500/[0.06] px-2 py-1 text-sm" data-row="answered" transition:fade={{ duration: ms }}>
			<span class="text-emerald-200">✓ {it.question}</span><span class="text-xs text-emerald-300/70">answered in your dictation</span>
		</div>
	{:else if listed.length}
		<div class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border-l-2 border-amber-400/80 bg-amber-500/[0.07] px-2 py-1.5" data-row="open" transition:fade={{ duration: ms }}>
			{#if label}<span class="text-[10px] font-semibold uppercase tracking-wide text-amber-300/90">{label}</span>{/if}
			<span class="text-sm font-medium text-amber-100">{it.question}</span>
			{#if it.why}<span class="cursor-help text-xs text-gray-500" title={it.why} aria-label="Why: {it.why}">ⓘ</span>{/if}
			<span class="flex min-w-0 flex-wrap items-center gap-1.5">
				{#each listed as s (s)}
					<span class="inline-flex items-center gap-0.5 rounded bg-white/[0.04] px-1.5 py-0.5 text-xs text-gray-200">
						{s}
						<button type="button" class="px-0.5 text-gray-500 hover:text-rose-300" title="Remove: never stated"
							aria-label="Remove {s}" onclick={() => onRemoveSentence(s)}>×</button>
					</span>
				{/each}
			</span>
			<span class="ml-auto flex gap-1.5">
				<button type="button" class="rounded-md border border-amber-300/40 bg-amber-400/15 px-2 py-0.5 text-xs font-medium text-amber-100 hover:bg-amber-400/25"
					title="Add: {listed.join(' ')}" onclick={() => onAnswer(it.id)}>{answerLabel(listed)}</button>
				<button type="button" class="rounded-md border border-white/10 px-2 py-0.5 text-xs text-gray-400 hover:bg-white/[0.06]"
					onclick={() => {
						newField?.focus();
						onDictateInto(it.region);
					}}>Dictate</button>
				<button type="button" class="rounded-md px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300"
					title={it.kind === 'referral' ? 'The scan cannot answer it: nothing is stated' : 'Not relevant: nothing is stated'}
					onclick={() => onSkip(it.id)}>{it.kind === 'referral' ? 'Not assessed' : 'Skip'}</button>
			</span>
		</div>
	{/if}
{/snippet}

{#snippet sentences(list: string[], key: string)}
	{@const q = expanded.includes(key) ? { shown: list, more: 0 } : quietLine(list)}
	{#each q.shown as s (s)}
		<span class="inline-flex items-center gap-0.5">
			<span class="text-gray-300/80 underline decoration-emerald-500/40 decoration-dashed underline-offset-4">{s}</span>
			<button type="button" class="rounded px-0.5 text-gray-600 hover:text-rose-300" title="Remove: never stated"
				aria-label="Remove {s}" onclick={() => onRemoveSentence(s)}>×</button>
		</span>
	{/each}
	{#if q.more}
		<button type="button" class="text-gray-500 hover:text-gray-300" onclick={() => (expanded = [...expanded, key])}>+{q.more} more</button>
	{/if}
{/snippet}

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
				<!-- The grouper's structure label is a tooltip, not text: it repeated the sentence (hand read 2026-10-12). -->
				<button type="button" class="w-full rounded px-1 text-left text-sm leading-6 text-gray-200 hover:bg-white/[0.05]" onclick={() => open(r)}
					title={r.structure ? `Placed as: ${r.structure}` : undefined}>
					{#if nested}<span aria-hidden="true" class="text-gray-500">↳ </span>{/if}{r.text}
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

	{#if referrals.length}
		<section aria-label="Referral question" class="space-y-1">{#each referrals as it (it.id)}{@render row(it, 'Referral')}{/each}</section>
	{/if}
	{#if looseRows.length}
		<section aria-label="Checks" class="space-y-1">{#each looseRows as it (it.id)}{@render row(it, it.region || null)}{/each}</section>
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
			appendNew(); // words typed or dictated into the field are never lost on blur
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
		{@const mine = ownMembers(g).flatMap((m) => rowsFor(m))}
		{@const normals = ownMembers(g).flatMap((m) => keptAssumed(m))}
		<section
			animate:flip={{ duration: ms }}
			transition:slide={{ duration: ms }}
			class="rounded {dragOver === g.name ? 'bg-emerald-500/10' : ''} {deleteRegion === g.name ? 'outline outline-1 outline-rose-500/60' : ''}"
			ondragover={(e) => {
				e.preventDefault();
				dragOver = g.name;
			}}
			ondragleave={() => (dragOver = null)}
			ondrop={(e) => drop(e, g.members[0])}
			aria-label={g.name}
		>
			<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">{g.name}</h3>
			<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
			{#if deleteRegion === g.name}
				<div class="mt-1 flex gap-2 px-1 text-xs">
					<button type="button" class="rounded bg-rose-500/20 px-2 py-0.5 text-rose-200" onclick={() => onDeleteRegion(g.name, true)}>Delete these lines</button>
					<button type="button" class="rounded px-2 py-0.5 text-gray-400 hover:text-gray-200" onclick={() => onDeleteRegion(g.name, false)}>Keep</button>
				</div>
			{/if}
			{#if mine.length}
				<div class="mt-1 space-y-1 px-1" aria-label="Questions for {g.name}">{#each mine as it (it.id)}{@render row(it, null)}{/each}</div>
			{/if}
			{#if normals.length}
				<p class="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-1 text-xs" data-quiet={g.name}>
					<span class="text-[10px] uppercase tracking-wide text-emerald-400/70">Will also be reported</span>
					{@render sentences(normals, g.name)}
				</p>
			{/if}
		</section>
	{/each}

	<!-- Normal regions (hand read 2026-10-12): what the radiologist said is normal, with their words beside it (a bare
	     pill read as missed); then the assumed regions together, tap one to see what will be reported. -->
	{#if trayRegions.length}
		{@const said = trayRegions.filter((r) => dictatedNormalWords.has(r))}
		{@const rest = trayRegions.filter((r) => !dictatedNormalWords.has(r))}
		<section aria-label="Normal regions" class="space-y-2 border-t border-white/5 pt-2">
			{#if said.length}
				<div class="space-y-1">
					<p class="text-[10px] uppercase tracking-wide text-gray-500">Normal, as you said</p>
					{#each said as r (r)}
						<div class="flex items-baseline gap-2 text-xs">
							<span class="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-emerald-200" data-state="dictated">{r}</span>
							<span class="min-w-0 truncate text-gray-400" title={dictatedNormalWords.get(r)?.join(' ')}>“{dictatedNormalWords.get(r)?.join(' ')}”</span>
						</div>
					{/each}
				</div>
			{/if}
			{#if rest.length}
				<div class="space-y-1.5">
					<p class="text-[10px] uppercase tracking-wide text-gray-500">{namedNormals ? 'Assumed normal (no sheet yet)' : 'Assumed normal: tap to see what will be reported'}</p>
					<div class="flex flex-wrap gap-1.5">
						{#each rest as r (r)}
							{@const none = !namedNormals && keptAssumed(r).length === 0}
							<!-- No transition on pills: a fade-out with flip left removed pills in the DOM (hand read 2026-10-11). -->
							<button
								type="button"
								class="rounded-full px-2 py-0.5 text-xs {none ? 'border border-white/10 text-gray-600'
									: 'border border-dashed border-white/20 text-gray-400 hover:border-emerald-400/40'} {openPill === r ? 'ring-1 ring-emerald-400/40' : ''}"
								title={keptAssumed(r).length ? `Will be reported: ${keptAssumed(r).join(' ')}` : none ? 'Nothing assumed: only what you dictate is reported' : 'Assumed normal (not dictated)'}
								data-state={none ? 'none' : 'assumed'}
								onclick={() => (openPill = openPill === r ? null : r)}>{r}</button>
						{/each}
					</div>
				</div>
			{/if}
			{#if openPill && keptAssumed(openPill).length}
				<p class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs" data-quiet={openPill}>
					<span class="text-[10px] uppercase tracking-wide text-emerald-400/70">{openPill} · will be reported</span>
					{@render sentences(keptAssumed(openPill), `tray:${openPill}`)}
				</p>
			{/if}
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

	<!-- Gate bar: the open questions and what will be assumed; Confirm takes ownership of both -->
	<section aria-label="Confirm" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2">
		<p class="flex flex-wrap gap-2 text-xs">
			<span class="rounded px-1.5 py-0.5 {openRows ? 'bg-amber-500/15 text-amber-200' : 'bg-white/5 text-gray-500'}">{openRows} referral {openRows === 1 ? 'question' : 'questions'} open</span>
			{#if reviewing}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">checking the findings…</span>
			{:else if reviewFailed}<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-rose-200" data-review="failed">checks unavailable: review the scan as usual</span>
			{:else if reviewWaiting}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-500">checks appear when you stop dictating</span>
			{:else if unanswered}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">{unanswered} {unanswered === 1 ? 'check' : 'checks'} unanswered (not stated)</span>{/if}
			<span class="rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300/90"
				>{gateConfirmed ? 'assumptions confirmed' : namedNormals ? `${assumedCount} regions assumed normal (no sheet yet)` : `${assumedCount} assumed normal`}</span>
			{#if !hasConclusion}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">no conclusion yet</span>{/if}
		</p>
		<button
			type="button"
			class="rounded-lg px-4 py-1.5 text-xs font-medium transition-colors {gateConfirmed
				? 'bg-emerald-500/20 text-emerald-200'
				: 'bg-purple-700 text-white hover:bg-purple-600 disabled:cursor-not-allowed disabled:opacity-40'}"
			disabled={gateConfirmed || openRows > 0 || !hasConclusion || syncing || newLine.trim().length > 0 || editing !== null}
			onclick={onConfirm}>{gateConfirmed ? 'Confirmed ✓' : syncing ? 'Updating…' : 'Confirm'}</button>
	</section>
</div>
