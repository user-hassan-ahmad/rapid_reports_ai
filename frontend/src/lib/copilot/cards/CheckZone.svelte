<script lang="ts">
	/**
	 * Check (spec 2026-10-14 §4.2, §6): only the values the radiologist must affirm before Apply. A decisive pre-filled
	 * or assumed value: ✓ records the tick on the card (nothing is sent). A scope doubt: Confirm sends the value as the
	 * radiologist's answer (it may then exclude). Change opens the input's own options. Read-only without handlers.
	 */
	import { shownValue } from './format';
	import type { CheckItem } from './questionnaire';
	import ValueEdit from './ValueEdit.svelte';

	let {
		items,
		guideline = '',
		onTick = null,
		onEdit = null
	}: {
		items: CheckItem[];
		guideline?: string;
		onTick?: ((input: string, value: string) => void) | null;
		onEdit?: ((input: string, value: string) => void) | null;
	} = $props();
	let editing = $state<string | null>(null);
	const from = (c: CheckItem) =>
		c.affirmed ? 'confirmed by you' : c.kind === 'doubt' ? `pre-filled · would make ${guideline || 'this guideline'} not apply` : c.kind === 'assumed' ? 'assumed' : c.basis || (c.byExam ? 'set by the exam' : 'pre-filled');
</script>

{#if items.length}
	<section class="cp-check" aria-label="Check" data-testid="cp-check">
		<div class="cp-label">Check</div>
		<ul class="cp-check-list">
			{#each items as c (c.input)}
				<li class="cp-check-item" class:cp-check-doubt={c.kind === 'doubt'} data-testid={c.kind === 'doubt' ? 'cp-scope-doubt' : 'cp-check-item'}>
					<span class="cp-check-text"><b>{c.label}: {shownValue(c.value)}</b> <span class="cp-muted">{from(c)}</span></span>
					{#if editing === c.input && onEdit}
						<ValueEdit label={c.label} value={c.value} options={c.options} onSave={(v) => { editing = null; onEdit?.(c.input, v); }} onCancel={() => (editing = null)} />
					{:else if onEdit}
						<span class="cp-check-actions">
							{#if c.kind === 'doubt'}
								<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onEdit?.(c.input, c.value)}>Confirm</button>
							{:else if !c.affirmed && onTick}
								<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onTick?.(c.input, c.value)}>✓</button>
							{/if}
							<button type="button" class="rv-btn" aria-label={`Change ${c.label}`} onclick={() => (editing = c.input)}>Change</button>
						</span>
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/if}

<style>
	.cp-check { display: flex; flex-direction: column; gap: 4px; font-size: 0.8125rem; }
	.cp-check-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
	.cp-check-item { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--rv-border); }
	.cp-check-doubt { border-color: color-mix(in srgb, var(--rv-amber-line) 55%, transparent); background: var(--rv-amber-bg); }
	.cp-check-actions { display: flex; gap: 6px; }
</style>
