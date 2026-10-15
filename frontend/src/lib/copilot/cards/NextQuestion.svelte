<script lang="ts">
	/**
	 * The next question (spec 2026-10-14 §4.3): the first input the engine still needs, the source's definition, the
	 * pack's own answers as buttons (a typed value only when it has none), "Not known" (sent as "Not stated"), and what
	 * the answer decides between. The parent keys it by input, so a typed value never carries over.
	 */
	import { NOT_STATED } from '../state';
	import type { Ask } from '../types';
	import { NOT_KNOWN, optionLabel } from './format';

	let { ask, onAnswer }: { ask: Ask; onAnswer: (input: string, value: string) => void } = $props();
	let typed = $state('');
	const options = $derived((ask.options ?? []).filter((o) => o !== NOT_STATED));
	const between = $derived([...new Set((ask.decides_between ?? []).map((d) => d.classification).filter(Boolean))]);
</script>

<section class="cp-question" aria-label="Next question" data-testid="cp-question">
	<p class="cp-p"><b>{ask.label}</b></p>
	{#if ask.definition?.text}<p class="cp-p cp-muted cp-q-def">{ask.definition.text}</p>{/if}
	<div class="cp-q-answers" role="group" aria-label={`Answer ${ask.label}`}>
		{#each options as o (o)}<button type="button" class="rv-btn" onclick={() => onAnswer(ask.input, o)}>{optionLabel(o)}</button>{/each}
		{#if !options.length}
			<input class="cp-edit-field" aria-label={`Value for ${ask.label}`} bind:value={typed} onkeydown={(e) => { if (e.key === 'Enter' && typed.trim()) onAnswer(ask.input, typed.trim()); }} />
			<button type="button" class="rv-btn" disabled={!typed.trim()} onclick={() => onAnswer(ask.input, typed.trim())}>Set</button>
		{/if}
		<button type="button" class="rv-btn" onclick={() => onAnswer(ask.input, NOT_STATED)}>{NOT_KNOWN}</button>
	</div>
	{#if between.length > 1}<p class="cp-p cp-muted cp-q-between">Decides between: {between.join(' · ')}</p>{/if}
</section>

<style>
	.cp-question { display: flex; flex-direction: column; gap: 4px; font-size: 0.8125rem; padding-top: 8px; border-top: 1px solid var(--rv-border); }
	.cp-q-def, .cp-q-between { font-size: 0.75rem; }
	.cp-q-answers { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
