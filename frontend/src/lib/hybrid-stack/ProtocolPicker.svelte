<script lang="ts">
	// Protocol picker (spec §3): typeahead on every keystroke, Jev re-rank after a pause, the protocol line in italics
	// under each option, phase variant and side chosen before the pick completes, "Not listed" keeps free text.
	// After "Use this protocol" the picker collapses to the committed pick (`value`) with a Change button; Change or a
	// new query clears the pick (onClear) until Use is pressed again, so what is shown is always what is committed.
	import { onMount, tick } from 'svelte';
	import { searchProtocols, postNotListed } from './api';
	import { pickSummary, type ProtocolOption, type ProtocolPick } from './protocol';

	let { token, value = null, query = '', disabled = false, onPick, onClear = () => {}, onNotListed }: {
		token: string | null; value?: ProtocolPick | null; query?: string; disabled?: boolean;
		onPick: (p: ProtocolPick) => void; onClear?: () => void; onNotListed: (q: string) => void;
	} = $props();

	let q = $state(value?.displayName ?? query);
	let editing = $state(!value);
	let options = $state<ProtocolOption[]>([]);
	let hint = $state(false);
	let chosen = $state<ProtocolOption | null>(null);
	let variant = $state(0);
	let side = $state<string | null>(null);
	let input = $state<HTMLInputElement | null>(null);
	let seq = 0;
	let localTimer: ReturnType<typeof setTimeout> | undefined;
	let rerankTimer: ReturnType<typeof setTimeout> | undefined;
	const committed = $derived(!editing && value ? value : null);

	async function run(text: string, rerank: boolean) {
		const mine = ++seq;
		try {
			const r = await searchProtocols(token, { q: text, rerank });
			if (mine !== seq) return;
			options = r.options;
			hint = r.not_listed_hint;
		} catch {
			if (mine === seq) options = [];
		}
	}

	function search() {
		clearTimeout(localTimer);
		clearTimeout(rerankTimer);
		if (!q.trim()) { options = []; hint = false; return; }
		localTimer = setTimeout(() => run(q, false), 120);
		rerankTimer = setTimeout(() => run(q, true), 450);
	}

	function onInput() {
		chosen = null;
		if (value) onClear(); // a new query: the old pick is no longer committed
		search();
	}

	// Typed text carried over from free text ("Pick from the library") is searched at once.
	onMount(() => { if (editing && q.trim()) search(); });

	async function change() {
		editing = true;
		chosen = null;
		q = value?.displayName ?? q;
		onClear();
		search();
		await tick();
		input?.focus();
	}

	function choose(o: ProtocolOption) {
		chosen = o;
		variant = 0;
		side = null;
	}

	const ready = $derived(!!chosen && (chosen.laterality !== 'required' || !!side));

	function use() {
		if (!chosen || !ready) return;
		const v = chosen.variants[variant];
		onPick({ id: chosen.id, phases: v.phases, laterality: chosen.laterality === 'required' ? side : null,
			displayName: chosen.display_name, line: v.line });
		editing = false;
	}

	function notListed() {
		void postNotListed(token, { q }).catch(() => {});
		onNotListed(q);
	}
</script>

{#if committed}
	<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-200" data-testid="protocol-committed">
		<span>{pickSummary(committed).name} · <em class="text-gray-400">{pickSummary(committed).line}</em></span>
		<button type="button" {disabled} onclick={change}
			class="rounded-md border border-white/15 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-40">Change</button>
	</div>
{:else}
<div class="grid gap-2">
	<input id="protocol-search" bind:this={input} role="combobox" aria-expanded={options.length > 0} aria-controls="protocol-options"
		autocomplete="off" placeholder="Start typing a protocol, e.g. CT abdomen and pelvis" bind:value={q} oninput={onInput} {disabled}
		onkeydown={(e) => { if (e.key === 'Enter') e.preventDefault(); }}
		class="input-dark w-full text-sm" />
	{#if options.length || q.trim()}
		<ul id="protocol-options" role="listbox" class="m-0 max-h-72 list-none overflow-auto rounded-lg border border-white/15 p-0">
			{#each options as o (o.id)}
				<li role="option" aria-selected={chosen?.id === o.id}>
					<button type="button" {disabled} onclick={() => choose(o)}
						class="grid w-full gap-0.5 px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5 focus-visible:bg-white/5 {chosen?.id === o.id ? 'bg-purple-500/15' : ''}">
						<span>{o.display_name}</span>
						<em class="text-xs text-gray-400">{o.protocol_line}</em>
					</button>
				</li>
			{/each}
			<li>
				<button type="button" {disabled} onclick={notListed}
					class="w-full border-t border-white/10 px-3 py-2 text-left text-xs text-gray-400 hover:bg-white/5 hover:text-gray-200">
					Not listed{hint ? ' (this looks like a different examination)' : ''}: type the scan type instead
				</button>
			</li>
		</ul>
	{/if}
	{#if chosen}
		<div class="grid gap-2 text-sm text-gray-300">
			{#if chosen.variants.length > 1}
				<fieldset class="flex flex-wrap gap-3 border-0 p-0"><legend class="mb-1 text-xs font-medium uppercase tracking-wider text-gray-400">Phases</legend>
					{#each chosen.variants as v, i (i)}
						<label class="flex items-center gap-1.5"><input type="radio" name="protocol-phase" {disabled} checked={variant === i} onchange={() => (variant = i)} /> <em>{v.line}</em></label>
					{/each}
				</fieldset>
			{/if}
			{#if chosen.laterality === 'required'}
				<fieldset class="flex flex-wrap gap-3 border-0 p-0"><legend class="mb-1 text-xs font-medium uppercase tracking-wider text-gray-400">Side</legend>
					{#each ['left', 'right', 'bilateral'] as s (s)}
						<label class="flex items-center gap-1.5"><input type="radio" name="protocol-side" {disabled} checked={side === s} onchange={() => (side = s)} /> {s[0].toUpperCase() + s.slice(1)}</label>
					{/each}
				</fieldset>
			{/if}
			<button type="button" disabled={disabled || !ready} onclick={use}
				class="justify-self-start rounded-lg bg-purple-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:cursor-not-allowed disabled:opacity-40">Use this protocol</button>
		</div>
	{/if}
</div>
{/if}
