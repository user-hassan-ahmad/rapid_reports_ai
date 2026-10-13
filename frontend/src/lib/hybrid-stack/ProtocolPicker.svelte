<script lang="ts">
	// Protocol picker (spec §3): typeahead on every keystroke, Jev re-rank after a pause, the protocol line in italics
	// under each option, phase variant and side chosen before the pick completes, "Not listed" keeps free text.
	import { searchProtocols, postNotListed } from './api';
	import type { ProtocolOption, ProtocolPick } from './protocol';

	let { token, value = null, onPick, onNotListed }: {
		token: string | null; value?: ProtocolPick | null; onPick: (p: ProtocolPick) => void; onNotListed: (q: string) => void;
	} = $props();

	let q = $state(value?.displayName ?? '');
	let options = $state<ProtocolOption[]>([]);
	let hint = $state(false);
	let chosen = $state<ProtocolOption | null>(null);
	let variant = $state(0);
	let side = $state<string | null>(null);
	let seq = 0;
	let localTimer: ReturnType<typeof setTimeout> | undefined;
	let rerankTimer: ReturnType<typeof setTimeout> | undefined;

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

	function onInput() {
		chosen = null;
		clearTimeout(localTimer);
		clearTimeout(rerankTimer);
		if (!q.trim()) { options = []; hint = false; return; }
		localTimer = setTimeout(() => run(q, false), 120);
		rerankTimer = setTimeout(() => run(q, true), 450);
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
	}

	function notListed() {
		void postNotListed(token, { q }).catch(() => {});
		onNotListed(q);
	}
</script>

<div class="grid gap-2">
	<input id="protocol-search" role="combobox" aria-expanded={options.length > 0} aria-controls="protocol-options"
		autocomplete="off" placeholder="Start typing a protocol, e.g. CT abdomen and pelvis" bind:value={q} oninput={onInput}
		class="input-dark w-full text-sm" />
	{#if options.length || q.trim()}
		<ul id="protocol-options" role="listbox" class="m-0 max-h-72 list-none overflow-auto rounded-lg border border-white/15 p-0">
			{#each options as o (o.id)}
				<li role="option" aria-selected={chosen?.id === o.id}>
					<button type="button" onclick={() => choose(o)}
						class="grid w-full gap-0.5 px-3 py-2 text-left text-sm text-gray-200 hover:bg-white/5 focus-visible:bg-white/5 {chosen?.id === o.id ? 'bg-purple-500/15' : ''}">
						<span>{o.display_name}</span>
						<em class="text-xs text-gray-400">{o.protocol_line}</em>
					</button>
				</li>
			{/each}
			<li>
				<button type="button" onclick={notListed}
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
						<label class="flex items-center gap-1.5"><input type="radio" name="protocol-phase" checked={variant === i} onchange={() => (variant = i)} /> <em>{v.line}</em></label>
					{/each}
				</fieldset>
			{/if}
			{#if chosen.laterality === 'required'}
				<fieldset class="flex flex-wrap gap-3 border-0 p-0"><legend class="mb-1 text-xs font-medium uppercase tracking-wider text-gray-400">Side</legend>
					{#each ['left', 'right', 'bilateral'] as s (s)}
						<label class="flex items-center gap-1.5"><input type="radio" name="protocol-side" checked={side === s} onchange={() => (side = s)} /> {s[0].toUpperCase() + s.slice(1)}</label>
					{/each}
				</fieldset>
			{/if}
			<button type="button" disabled={!ready} onclick={use}
				class="justify-self-start rounded-lg bg-purple-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:cursor-not-allowed disabled:opacity-40">Use this protocol</button>
		</div>
	{/if}
</div>
