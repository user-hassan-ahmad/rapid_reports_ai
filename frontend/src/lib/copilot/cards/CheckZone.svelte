<script lang="ts">
	/**
	 * Check (spec 2026-10-14 §4.2, §6): only the values the radiologist must affirm before Apply. A decisive pre-filled
	 * or assumed value: ✓ records the tick on the card (nothing is sent). A scope doubt: Confirm sends the value as the
	 * radiologist's answer (it may then exclude). Change opens the input's own options. Read-only without handlers.
	 */
	import { shownValue } from './format';
	import type { CheckItem } from './questionnaire';
	import Icon from './Icon.svelte';
	import ValueEdit from './ValueEdit.svelte';

	let {
		items,
		guideline = '',
		onTick = null,
		onEdit = null,
		showLabel = true
	}: {
		items: CheckItem[];
		guideline?: string;
		onTick?: ((input: string, value: string) => void) | null;
		onEdit?: ((input: string, value: string) => void) | null;
		/** The status line above already says "Check N values to apply": the zone is named only when it does not. */
		showLabel?: boolean;
	} = $props();
	let editing = $state<string | null>(null);
	const from = (c: CheckItem) =>
		c.affirmed ? 'confirmed by you' : c.kind === 'doubt' ? `pre-filled · would make ${guideline || 'this guideline'} not apply` : c.kind === 'assumed' ? 'assumed' : c.basis || (c.byExam ? 'set by the exam' : 'pre-filled');
</script>

{#if items.length}
	<section class="cp-check" aria-label="Check" data-testid="cp-check">
		{#if showLabel}<div class="cp-label" data-testid="cp-check-label">Check</div>{/if}
		<ul class="cp-check-list">
			{#each items as c (c.input)}
				<li class="cp-check-item" class:cp-check-doubt={c.kind === 'doubt'} data-testid={c.kind === 'doubt' ? 'cp-scope-doubt' : 'cp-check-item'}>
					<span class="cp-check-text"><b>{c.label}: {shownValue(c.value)}</b> <span class="cp-muted">{from(c)}</span></span>
					{#if editing === c.input && onEdit}
						<ValueEdit label={c.label} value={c.value} options={c.options} onSave={(v) => { editing = null; onEdit?.(c.input, v); }} onCancel={() => (editing = null)} />
					{:else if onEdit}
						<span class="cp-check-actions">
							{#if c.kind === 'doubt'}
								{#if c.value}<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onEdit?.(c.input, c.value)}>Confirm</button>{/if}
							{:else if !c.affirmed && onTick}
								<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onTick?.(c.input, c.value)}>✓</button>
							{/if}
							<button type="button" class="rv-btn cp-check-change" aria-label={`Change ${c.label}`} title={`Change ${c.label}`} onclick={() => (editing = c.input)}><Icon name="edit" size={13} /></button>
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
	.cp-check-item { display: grid; grid-template-columns: 1fr auto; align-items: start; gap: 6px; padding: 6px 8px; border-radius: 8px; border: 1px solid var(--rv-border); }
	.cp-check-text { min-width: 0; overflow-wrap: anywhere; }
	.cp-check-item > :global(:not(.cp-check-text):not(.cp-check-actions)) { grid-column: 1 / -1; }
	.cp-check-doubt { border-color: color-mix(in srgb, var(--rv-amber-line) 55%, transparent); background: var(--rv-amber-bg); }
	.cp-check-actions { display: flex; gap: 6px; }
</style>
