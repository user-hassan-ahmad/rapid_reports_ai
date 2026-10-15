<script lang="ts">
	/** The answers given so far (spec 2026-10-14 §4.3): one chip each; a tap opens that answer's options. `editing` is
	 *  bindable so the result's "Answer [question] to apply" can open a chip. */
	import { NOT_KNOWN, displayValue } from './format';
	import { NOT_STATED } from '../state';
	import type { Chip } from './questionnaire';
	import ValueEdit from './ValueEdit.svelte';

	let { chips, editing = $bindable(null), onAnswer }: { chips: Chip[]; editing?: string | null; onAnswer: (input: string, value: string) => void } = $props();
</script>

{#if chips.length}
	<span class="cp-chips-label cp-muted">Your answers</span>
	<ul class="cp-chips" aria-label="Your answers" data-testid="cp-answers">
		{#each chips as c (c.input)}
			<li>
				{#if editing === c.input}
					<ValueEdit label={c.label} value={c.value} options={c.options} onSave={(v) => { editing = null; onAnswer(c.input, v); }} onCancel={() => (editing = null)} />
				{:else}
					<button type="button" class="cp-chip" aria-label={`Change ${c.label}: ${c.value === NOT_STATED ? NOT_KNOWN : displayValue(c.value, c.basis)}`} onclick={() => (editing = c.input)}>{c.label}: {c.value === NOT_STATED ? NOT_KNOWN : displayValue(c.value, c.basis)} ✎</button>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.cp-chips-label { font-size: 0.75rem; }
	.cp-chips { margin: 0; padding: 0; list-style: none; display: flex; flex-wrap: wrap; gap: 4px; font-size: 0.75rem; }
</style>
